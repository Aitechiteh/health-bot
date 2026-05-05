#!/usr/bin/env python3
"""
Longevity Parser — сбор новостей из RSS/X/YouTube всех longevity-организаций.
Сохраняет в SQLite для последующего AI-курирования.
"""

import sys, json, time, re
from datetime import datetime, date
from urllib.request import Request, urlopen
from pathlib import Path

# Настройки
DB_PATH = Path(__file__).parent / "health.db"
SOURCES_PATH = Path(__file__).parent / "longevity_sources.json"
LITELLM_KEY = "sk-4e9e073d30502f092ffd3ddfa29e9c46"

# Импортируем feedparser (pip install feedparser --break-system-packages)
import feedparser
import sqlite3


def get_db():
    return sqlite3.connect(str(DB_PATH))


def init_schema():
    """Создать таблицу для longevity-новостей."""
    db = get_db()
    db.execute("""
        CREATE TABLE IF NOT EXISTS longevity_news (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id TEXT NOT NULL,
            source_name TEXT,
            title TEXT,
            url TEXT UNIQUE,
            published TEXT,
            summary TEXT,
            content TEXT,
            category TEXT DEFAULT 'longevity',
            curated INTEGER DEFAULT 0,
            curator_notes TEXT,
            relevance_score REAL DEFAULT 0,
            extracted_fact TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS longevity_sources_meta (
            source_id TEXT PRIMARY KEY,
            last_fetched TIMESTAMP,
            total_items INTEGER DEFAULT 0,
            new_items INTEGER DEFAULT 0,
            error TEXT
        )
    """)
    db.commit()
    db.close()


def fetch_rss(url: str, source_id: str) -> list:
    """Собрать статьи из RSS-ленты."""
    try:
        feed = feedparser.parse(url)
        entries = []

        for e in feed.entries:
            published = None
            if hasattr(e, 'published_parsed') and e.published_parsed:
                published = time.strftime('%Y-%m-%d %H:%M:%S', e.published_parsed)
            elif hasattr(e, 'updated_parsed') and e.updated_parsed:
                published = time.strftime('%Y-%m-%d %H:%M:%S', e.updated_parsed)

            summary = ""
            if hasattr(e, 'summary'):
                summary = re.sub(r'<[^>]+>', '', e.summary)[:500]
            elif hasattr(e, 'description'):
                summary = re.sub(r'<[^>]+>', '', e.description)[:500]

            entries.append({
                "source_id": source_id,
                "title": e.get('title', 'No title'),
                "url": e.get('link', ''),
                "published": published,
                "summary": summary,
                "content": "",
            })

        return entries
    except Exception as ex:
        print(f"RSS fetch error ({url}): {ex}", file=sys.stderr)
        return []


def deduplicate_and_save(entries: list) -> int:
    """Сохранить только новые статьи в БД."""
    saved = 0
    db = get_db()

    for entry in entries:
        if not entry["url"]:
            continue

        # Проверить — уже есть?
        exists = db.execute(
            "SELECT id FROM longevity_news WHERE url = ?",
            (entry["url"],)
        ).fetchone()

        if exists:
            continue

        db.execute("""
            INSERT INTO longevity_news 
            (source_id, source_name, title, url, published, summary, content)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            entry["source_id"],
            entry.get("source_name", ""),
            entry["title"],
            entry["url"],
            entry["published"],
            entry["summary"],
            entry.get("content", ""),
        ))
        saved += 1

    db.commit()
    db.close()
    return saved


def fetch_youtube_channel(channel_id: str, max_results: int = 20) -> list:
    """Собрать последние видео с YouTube-канала через парсинг страницы."""
    entries = []
    try:
        url = f"https://www.youtube.com/@{channel_id}/videos"
        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=30) as resp:
            html = resp.read().decode('utf-8', errors='ignore')
        
        # Ищем JSON с видео в странице
        m = re.search(r'var ytInitialData = ({.*?});</script>', html)
        if not m:
            return entries
        
        data = json.loads(m.group(1))
        tabs = (
            data.get("contents", {})
            .get("twoColumnBrowseResultsRenderer", {})
            .get("tabs", [])
        )
        
        for tab in tabs:
            rich_grid = (
                tab.get("tabRenderer", {})
                .get("content", {})
                .get("richGridRenderer", {})
            )
            for item in rich_grid.get("contents", []):
                video = item.get("richItemRenderer", {}).get("content", {}).get("videoRenderer", {})
                if video:
                    vid = video.get("videoId", "")
                    title = video.get("title", {}).get("runs", [{}])[0].get("text", "")
                    entries.append({
                        "title": title,
                        "url": f"https://www.youtube.com/watch?v={vid}" if vid else "",
                        "published": "",
                        "summary": title,
                        "content": "",
                    })
                    if len(entries) >= max_results:
                        return entries
        
        return entries
    except Exception as ex:
        print(f"YouTube fetch error ({channel_id}): {ex}", file=sys.stderr)
        return []


def fetch_x_profile(handle: str, max_results: int = 10) -> list:
    """Собрать твиты через Nitter (no API key needed)."""
    entries = []
    try:
        url = f"https://nitter.net/{handle}"
        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=30) as resp:
            html = resp.read().decode('utf-8', errors='ignore')
        
        tweets = re.findall(
            r'<div class="tweet-content[^"]*"[^>]*>(.*?)</div>\s*<span class="tweet-date"><a[^>]*href="([^"]+)"',
            html, re.DOTALL
        )
        
        for content, link in tweets[:max_results]:
            text = re.sub(r'<[^>]+>', '', content).strip()[:300]
            entries.append({
                "title": text[:100],
                "url": f"https://nitter.net{link}" if link.startswith('/') else link,
                "published": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                "summary": text,
                "content": text,
            })
        
        return entries
    except Exception as ex:
        print(f"X fetch error ({handle}): {ex}", file=sys.stderr)
        return []


def run_curator_batch(limit: int = 10):
    """AI-куратор: классифицировать и извлекать факты из неразобранных новостей."""
    db = get_db()
    
    uncurated = db.execute("""
        SELECT id, source_id, title, url, summary
        FROM longevity_news
        WHERE curated = 0
        ORDER BY published DESC
        LIMIT ?
    """, (limit,)).fetchall()
    
    if not uncurated:
        db.close()
        print("No uncurated news — all clean.")
        return
    
    print(f"Curating {len(uncurated)} news items via AI...")
    
    articles_text = "\n\n".join(
        f"ID={r[0]} | {r[1]} | {r[2]}\nSUMMARY={(r[4] or '')[:300]} | URL={r[3]}"
        for r in uncurated
    )
    
    prompt = f"""Ты — куратор longevity-новостей. Проанализируй статьи и для каждой укажи:

1. relevance_score (0-10): насколько это важно для долголетия/anti-aging
2. category (одно из: supplements, nutrition, exercise, sleep, biomarkers, drugs, research, policy, clinic, other)
3. extracted_fact (1-2 предложения ключевого вывода на русском)

Формат ответа — JSON массив:
[{{"id": ID, "relevance_score": X, "category": "Y", "extracted_fact": "Z"}}, ...]

СТАТЬИ:
{articles_text}

ОТВЕТ (только JSON):"""

    try:
        data = json.dumps({
            "model": "gemma4:31b",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3, "max_tokens": 2000,
        }).encode()

        req = Request("http://127.0.0.1:4000/chat/completions", data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Authorization", f"Bearer {LITELLM_KEY}")

        with urlopen(req, timeout=180) as resp:
            body = json.loads(resp.read())
            raw = body["choices"][0]["message"]["content"]
        
        # Извлечь JSON (может быть обёрнуто в ```)
        json_match = re.search(r'\[.*\]', raw, re.DOTALL)
        if json_match:
            parsed = json.loads(json_match.group(0))
        else:
            parsed = json.loads(raw)

        # Сохранить результаты
        for i, item in enumerate(parsed):
            row = uncurated[i] if i < len(uncurated) else None
            if row is None:
                continue
            db.execute("""
                UPDATE longevity_news
                SET curated = 1,
                    relevance_score = ?,
                    category = ?,
                    extracted_fact = ?,
                    curator_notes = ?
                WHERE id = ?
            """, (
                item.get("relevance_score", 0),
                item.get("category", "other"),
                item.get("extracted_fact", ""),
                json.dumps(item, ensure_ascii=False),
                row[0],
            ))

        db.commit()
        print(f"Curated {len(parsed)} articles.")
    except Exception as ex:
        print(f"Curator error: {ex}", file=sys.stderr)
        for r in uncurated:
            db.execute(
                "UPDATE longevity_news SET curated = 1, curator_notes = ? WHERE id = ?",
                (f"curation_error: {str(ex)[:200]}", r[0])
            )
        db.commit()
    
    db.close()


def main():
    """Главный цикл: сбор RSS + YouTube + X → сохранение → куратор."""
    init_schema()
    
    with open(SOURCES_PATH) as f:
        sources = json.load(f)["sources"]
    
    total_new = 0
    
    for source in sources:
        sid = source["id"]
        print(f"\n{source['name']} ({sid})")
        
        new_count = 0
        
        # RSS
        rss_url = source.get("rss")
        if rss_url:
            print(f"  RSS: {rss_url}")
            try:
                entries = fetch_rss(rss_url, sid)
                for e in entries:
                    e["source_name"] = source["name"]
                saved = deduplicate_and_save(entries)
                print(f"  → {len(entries)} fetched, {saved} new")
                new_count += saved
            except Exception as ex:
                print(f"  RSS error: {ex}")
        
        # YouTube
        yt = source.get("youtube_channel")
        if yt:
            channel_name = yt.split('@')[-1] if '@' in yt else yt
            print(f"  YouTube: {channel_name}")
            entries = fetch_youtube_channel(channel_name, max_results=10)
            for e in entries:
                e["source_id"] = sid
                e["source_name"] = source["name"]
            saved = deduplicate_and_save(entries)
            print(f"  → {len(entries)} fetched, {saved} new")
            new_count += saved
        
        # X/Twitter
        x_handle = source.get("x_handle")
        if x_handle:
            print(f"  X: @{x_handle}")
            entries = fetch_x_profile(x_handle, max_results=5)
            for e in entries:
                e["source_id"] = sid
                e["source_name"] = source["name"]
            saved = deduplicate_and_save(entries)
            print(f"  → {len(entries)} fetched, {saved} new")
            new_count += saved
        
        # Обновить мету
        db = get_db()
        db.execute("""
            INSERT OR REPLACE INTO longevity_sources_meta
            (source_id, last_fetched, total_items, new_items)
            VALUES (?, ?, 
                (SELECT COALESCE(total_items, 0) + ? FROM longevity_sources_meta WHERE source_id = ?),
                ?)
        """, (sid, datetime.now().isoformat(), new_count, sid, new_count))
        db.commit()
        db.close()
        
        total_new += new_count
    
    print(f"\n{'='*50}")
    print(f"TOTAL: {total_new} new articles from {len(sources)} sources")
    
    if total_new > 0:
        print("\nRunning AI curator...")
        run_curator_batch(limit=min(total_new, 5))
    
    print("\nDone.")


if __name__ == "__main__":
    main()
