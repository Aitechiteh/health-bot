#!/usr/bin/env python3
"""Health Digest — сбор видео + AI-анализ через LiteLLM → БД + Telegram."""

import json, sqlite3, time, os
from pathlib import Path
from datetime import date
from env_utils import env_value

DB = Path("/root/herm/health-bot/health.db")
API_URL = os.getenv("API_URL", "http://127.0.0.1:8082")
BOT_TOKEN = env_value("BOT_TOKEN", Path(__file__).with_name(".env"))
CHAT_ID = os.getenv("CHAT_ID", "167413129")  # @health_alex_bot chat

CHANNELS = {
    # Персональные health-каналы
    "@Max_Pogorely": "https://www.youtube.com/@Max_Pogorely/videos",
    "@DrEricBerg": "https://www.youtube.com/@DrEricBerg/videos",
    "@eokomarovskiy": "https://www.youtube.com/@eokomarovskiy/videos",
    # Университеты и научные институты (longevity/anti-aging)
    "@NIHAging": "https://www.youtube.com/@NIHAging/videos",
    "@BuckInstitute": "https://www.youtube.com/@BuckInstitute/videos",
    "@harvardmedicalschool": "https://www.youtube.com/@harvardmedicalschool/videos",
    "@StanfordMedicine": "https://www.youtube.com/@StanfordMedicine/videos",
    "@mayoclinic": "https://www.youtube.com/@mayoclinic/videos",
    "@UniofOxford": "https://www.youtube.com/@UniofOxford/videos",
    "@CambridgeUniversity": "https://www.youtube.com/@CambridgeUniversity/videos",
    "@USCLeonardDavis": "https://www.youtube.com/@USCLeonardDavis/videos",
    "@YaleMedicine": "https://www.youtube.com/@YaleMedicine/videos",
    "@salkinstitute": "https://www.youtube.com/@salkinstitute/videos",
}

LLM_KEY = env_value("LITELLM_MASTER_KEY", Path("/root/.hermes/.env"))
HEADERS = {"Content-Type": "application/json", "Authorization": f"Bearer {LLM_KEY}"}
LLM_URL = "http://127.0.0.1:4001/v1/chat/completions"
LLM_MODEL = "deepseek-v4-flash"

def collect_videos():
    """Собрать топ-5 видео с каждого канала через yt-dlp."""
    import subprocess, json as j
    
    all_videos = []
    for channel, url in CHANNELS.items():
        try:
            result = subprocess.run([
                "yt-dlp", "--flat-playlist", "--dump-json",
                "--playlist-end", "5", url
            ], capture_output=True, text=True, timeout=45)
            
            for line in result.stdout.strip().split("\n"):
                if not line: continue
                v = j.loads(line)
                all_videos.append({
                    "channel": channel,
                    "id": v.get("id"),
                    "title": v.get("title", ""),
                    "url": f"https://youtube.com/watch?v={v.get('id')}",
                    "description": (v.get("description") or "")[:500],
                    "duration": v.get("duration", 0),
                    "view_count": v.get("view_count"),
                })
        except Exception as e:
            print(f"⚠️ {channel}: {e}")
    
    print(f"✅ Собрано {len(all_videos)} видео")
    return all_videos


def call_llm(prompt: str) -> str:
    """Запрос к LiteLLM через рабочую модель."""
    import urllib.request, json as j
    
    for model in dict.fromkeys((LLM_MODEL, "deepseek-v4-pro", "kimi-k2.6")):
        data = j.dumps({
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
            "max_tokens": 4000,
        }).encode()
        req = urllib.request.Request(LLM_URL, data=data, headers=HEADERS, method="POST")
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=120) as resp:
                    body = j.loads(resp.read())
                    content = body["choices"][0]["message"].get("content") or ""
                if content.strip():
                    return content
                raise ValueError("empty model response")
            except Exception as e:
                print(f"  {model} attempt {attempt+1}: {e}")
                time.sleep(5)
    
    return ""


def parse_json_value(raw: str):
    """Return the first complete JSON value from a model response."""
    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
    decoder = json.JSONDecoder()
    for index, char in enumerate(raw):
        if char not in "[{":
            continue
        try:
            return decoder.raw_decode(raw[index:])[0]
        except json.JSONDecodeError:
            continue
    raise ValueError("LLM response contains no complete JSON value")


def analyze_video(video: dict) -> list:
    """AI-анализ одного видео: факты + credibility."""
    prompt = f"""Проанализируй видео по здоровью/биохакингу.

НАЗВАНИЕ: {video['title']}
ОПИСАНИЕ: {video['description'][:500]}
КАНАЛ: {video['channel']}

Выдели 3-5 ключевых научных фактов из названия и описания. 
Для каждого факта:
- fact: сам факт (кратко, 1-2 предложения)
- recommendation: практическая рекомендация для здоровья (1 предложение)
- credibility: оценка достоверности 0.0-1.0 (учитывай репутацию канала: @DrEricBerg=0.9, @eokomarovskiy=0.85, @Max_Pogorely=0.8)

Ответ СТРОГО в JSON (без markdown): [{{"fact":"...","recommendation":"...","credibility":X.X}}]"""
    
    raw = call_llm(prompt)
    try:
        facts = parse_json_value(raw)
        if not isinstance(facts, list):
            raise ValueError("LLM response is not a JSON list")
        valid = []
        for fact in facts:
            if not isinstance(fact, dict) or not str(fact.get("fact") or "").strip():
                continue
            try:
                credibility = float(fact["credibility"])
            except (KeyError, TypeError, ValueError):
                continue
            if 0.0 <= credibility <= 1.0:
                valid.append({**fact, "credibility": credibility})
        return valid
    except (json.JSONDecodeError, TypeError, ValueError, IndexError):
        identity = video.get("id") or video.get("url") or "unknown"
        print(f"  ⚠️ JSON parse failed for {identity}, raw: {raw[:200]}")
        return []


def save_to_db(video: dict, facts: list):
    """Сохранить факты в youtube_sources."""
    if not facts:
        return False
    db = sqlite3.connect(str(DB))
    avg_cred = sum(f["credibility"] for f in facts) / len(facts)
    
    db.execute(
        """INSERT INTO youtube_sources
           (channel_name, video_url, transcript, facts_json, credibility_score, analyzed)
           VALUES (?, ?, ?, ?, ?, 1)
           ON CONFLICT(video_url) DO UPDATE SET
             channel_name=excluded.channel_name,
             transcript=excluded.transcript,
             facts_json=excluded.facts_json,
             credibility_score=excluded.credibility_score,
             analyzed=1""",
        (video["channel"], video["url"], video["description"], json.dumps(facts, ensure_ascii=False), avg_cred)
    )
    db.commit()
    db.close()
    return True


def send_telegram(text: str):
    """Отправить сообщение в Telegram через @health_alex_bot."""
    from urllib.request import Request, urlopen
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    chunks = [text[i:i + 4000] for i in range(0, len(text), 4000)] or [""]
    for chunk in chunks:
        data = json.dumps({"chat_id": CHAT_ID, "text": chunk}).encode()
        req = Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        try:
            with urlopen(req, timeout=10) as resp:
                body = json.loads(resp.read())
            if not body.get("ok"):
                print(f"❌ Telegram error: {body.get('description')}")
                return False
        except Exception as e:
            print(f"❌ Send error: {e}")
            return False
    print(f"✅ Digest sent to Telegram ({len(chunks)} part(s))")
    return True


def format_digest(results: list) -> str:
    """Сформировать текстовый дайджест для Telegram."""
    today = date.today().strftime("%d.%m.%Y")
    lines = [f"📋 Health Digest — {today}\n"]
    
    for r in results:
        video = r["video"]
        facts = r["facts"]
        if not facts:
            continue
        
        channel_emoji = {"@DrEricBerg": "🇺🇸", "@eokomarovskiy": "🇺🇦", "@Max_Pogorely": "🇷🇺"}.get(video["channel"], "🎬")
        lines.append(f"\n{channel_emoji} {video['title'][:80]}")
        lines.append(f"👀 {video.get('view_count', '?')} просмотров | {video['url']}")
        
        for i, f in enumerate(facts[:3], 1):
            cred_stars = "⭐" * round(f["credibility"] * 5)
            lines.append(f"  {i}. {f['fact']}")
            lines.append(f"  💡 {f['recommendation']} {cred_stars}")
    
    lines.append(f"\n━━━━━━━━━━━\n🔬 Powered by AI ({LLM_MODEL}) — {len(results)} видео")
    return "\n".join(lines)


def main():
    print("=" * 50)
    print("🏥 Health Digest Pipeline")
    print("=" * 50)
    
    # Шаг 1: Сбор видео
    print("\n📥 Сбор видео...")
    videos = collect_videos()
    
    # Шаг 2: AI-анализ
    print("\n🧠 AI-анализ...")
    results = []
    failures = 0
    for i, v in enumerate(videos, 1):
        print(f"  [{i}/{len(videos)}] {v['title'][:60]}...")
        facts = analyze_video(v)
        print(f"    → {len(facts)} фактов")
        if facts:
            save_to_db(v, facts)
        else:
            failures += 1
        results.append({"video": v, "facts": facts})
    
    # Шаг 3: Формирование дайджеста
    digest = format_digest(results)
    
    # Шаг 4: Отправка text+voice
    print(f"\n📤 Отправка в Telegram (чат {CHAT_ID})...")
    delivered = send_telegram(digest)
    # send_voice(digest)
    
    # Статистика
    total_facts = sum(len(r["facts"]) for r in results)
    print(f"\n✅ Готово: {len(videos)} видео, {total_facts} фактов")
    if failures or not delivered:
        print(f"❌ Не проанализировано видео: {failures}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
