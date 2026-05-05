#!/usr/bin/env python3
"""Health Digest — сбор видео + AI-анализ через LiteLLM → БД + Telegram."""

import json, sqlite3, time, os
from pathlib import Path
from datetime import date

DB = Path("/root/herm/health-bot/health.db")
API_URL = os.getenv("API_URL", "http://127.0.0.1:8082")
BOT_TOKEN = os.getenv("BOT_TOKEN", "8596541755:AAF9G9jv2EShD2bA5z3GDxLcMewy6aHkjio")
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

HEADERS = {"Content-Type": "application/json", "Authorization": "Bearer sk-4e9e073d30502f092ffd3ddfa29e9c46"}
LLM_URL = "http://127.0.0.1:4000/chat/completions"

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
    """Запрос к LiteLLM gemma4:31b."""
    import urllib.request, json as j
    
    data = j.dumps({
        "model": "openai/gemma4:31b",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 2000,
    }).encode()
    
    req = urllib.request.Request(LLM_URL, data=data, headers=HEADERS, method="POST")
    
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                body = j.loads(resp.read())
                return body["choices"][0]["message"]["content"]
        except Exception as e:
            print(f"  LLM attempt {attempt+1}: {e}")
            time.sleep(5)
    
    return "[]"


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
        # Clean markdown wrappers
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1]
            if raw.endswith("```"):
                raw = raw[:-3]
        return json.loads(raw)
    except:
        print(f"  ⚠️ JSON parse failed for {video['id']}, raw: {raw[:200]}")
        return []


def save_to_db(video: dict, facts: list):
    """Сохранить факты в youtube_sources."""
    db = sqlite3.connect(str(DB))
    avg_cred = sum(f["credibility"] for f in facts) / len(facts) if facts else 0
    
    db.execute(
        "INSERT INTO youtube_sources (channel_name, video_url, transcript, facts_json, credibility_score, analyzed) VALUES (?, ?, ?, ?, ?, 1)",
        (video["channel"], video["url"], video["description"], json.dumps(facts, ensure_ascii=False), avg_cred)
    )
    db.commit()
    db.close()


def send_telegram(text: str):
    """Отправить сообщение в Telegram. Через cron deliver='origin' само доставит."""
    print(text)  # cron job сам отправит через deliver=origin


def format_digest(results: list) -> str:
    """Сформировать HTML-дайджест для Telegram."""
    today = date.today().strftime("%d.%m.%Y")
    lines = [f"📋 <b>Health Digest — {today}</b>\n"]
    
    for r in results:
        video = r["video"]
        facts = r["facts"]
        if not facts:
            continue
        
        channel_emoji = {"@DrEricBerg": "🇺🇸", "@eokomarovskiy": "🇺🇦", "@Max_Pogorely": "🇷🇺"}.get(video["channel"], "🎬")
        lines.append(f"\n{channel_emoji} <b>{video['title'][:80]}</b>")
        lines.append(f"👀 {video.get('view_count', '?')} просмотров | <a href='{video['url']}'>смотреть</a>")
        
        for i, f in enumerate(facts[:3], 1):
            cred_stars = "⭐" * round(f["credibility"] * 5)
            lines.append(f"  {i}. {f['fact']}")
            lines.append(f"  💡 <i>{f['recommendation']}</i> {cred_stars}")
    
    lines.append(f"\n━━━━━━━━━━━\n🔬 <i>Powered by AI (gemma4:31b) — {len(results)} видео</i>")
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
    for i, v in enumerate(videos, 1):
        print(f"  [{i}/{len(videos)}] {v['title'][:60]}...")
        facts = analyze_video(v)
        print(f"    → {len(facts)} фактов")
        save_to_db(v, facts)
        results.append({"video": v, "facts": facts})
    
    # Шаг 3: Формирование дайджеста
    digest = format_digest(results)
    
    # Шаг 4: Отправка
    print(f"\n📤 Отправка в Telegram (чат {CHAT_ID})...")
    send_telegram(digest)
    
    # Статистика
    total_facts = sum(len(r["facts"]) for r in results)
    print(f"\n✅ Готово: {len(videos)} видео, {total_facts} фактов")


if __name__ == "__main__":
    main()
