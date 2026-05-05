#!/usr/bin/env python3
"""Сбор исторических видео (50+ с канала) + AI-анализ в фоне."""
import json, subprocess, sqlite3, urllib.request, time, os
from pathlib import Path
from datetime import date

DB = Path("/root/herm/health-bot/health.db")
LLM_URL = "http://127.0.0.1:4000/chat/completions"
HEADERS = {"Content-Type": "application/json", "Authorization": "Bearer ollama"}

CHANNELS = {
    "@Max_Pogorely": "https://www.youtube.com/@Max_Pogorely/videos",
    "@DrEricBerg": "https://www.youtube.com/@DrEricBerg/videos",
    "@eokomarovskiy": "https://www.youtube.com/@eokomarovskiy/videos",
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

def already_analyzed(video_id: str) -> bool:
    db = sqlite3.connect(str(DB))
    count = db.execute("SELECT COUNT(*) FROM youtube_sources WHERE video_url LIKE ?", (f"%{video_id}%",)).fetchone()[0]
    db.close()
    return count > 0

def fetch_videos(channel: str, url: str, limit: int = 50) -> list:
    result = subprocess.run([
        "yt-dlp", "--flat-playlist", "--dump-json",
        "--playlist-end", str(limit), url
    ], capture_output=True, text=True, timeout=60)
    
    videos = []
    for line in result.stdout.strip().split("\n"):
        if not line: continue
        v = json.loads(line)
        vid = v.get("id")
        if already_analyzed(vid):
            continue
        videos.append({
            "channel": channel,
            "id": vid,
            "title": v.get("title", ""),
            "url": f"https://youtube.com/watch?v={vid}",
            "description": (v.get("description") or "")[:500],
            "duration": v.get("duration", 0),
            "view_count": v.get("view_count"),
        })
    return videos

def call_llm(prompt: str) -> str:
    data = json.dumps({
        "model": "openai/gemma4:31b",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3, "max_tokens": 2000,
    }).encode()
    req = urllib.request.Request(LLM_URL, data=data, headers=HEADERS, method="POST")
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read())["choices"][0]["message"]["content"]
        except Exception as e:
            print(f"  LLM retry {attempt+1}: {e}")
            time.sleep(5)
    return "[]"

def analyze(video: dict) -> list:
    prompt = f"""Анализ видео по здоровью: {video['title']}
ОПИСАНИЕ: {video['description'][:500]}
КАНАЛ: {video['channel']}

Выдели 3-5 ключевых научных фактов. JSON: [{{"fact":"...","recommendation":"...","credibility":X.X}}]"""
    raw = call_llm(prompt)
    try:
        raw = raw.strip().lstrip("```json").rstrip("```").strip()
        return json.loads(raw)
    except:
        return []

def save(video: dict, facts: list):
    db = sqlite3.connect(str(DB))
    avg_cred = sum(f["credibility"] for f in facts) / len(facts) if facts else 0
    db.execute(
        "INSERT INTO youtube_sources (channel_name, video_url, transcript, facts_json, credibility_score, analyzed) VALUES (?, ?, ?, ?, ?, 1)",
        (video["channel"], video["url"], video["description"], json.dumps(facts, ensure_ascii=False), avg_cred)
    )
    db.commit()
    db.close()

total_processed = 0
total_facts = 0

for channel, url in CHANNELS.items():
    print(f"\n{'='*50}")
    print(f"📥 {channel}: сбор истории...")
    videos = fetch_videos(channel, url, 50)
    print(f"  → {len(videos)} новых видео для анализа")
    
    for i, v in enumerate(videos, 1):
        print(f"  [{i}/{len(videos)}] {v['title'][:70]}...")
        facts = analyze(v)
        save(v, facts)
        total_processed += 1
        total_facts += len(facts)
        print(f"    → {len(facts)} фактов")
        time.sleep(0.5)  # rate-limit

print(f"\n{'='*50}")
print(f"✅ Итого: {total_processed} видео, {total_facts} фактов")
