#!/usr/bin/env python3
"""
🔬 Fact Checker v2 — батчевый анализ health-фактов через LiteLLM (gemma4:31b).
Берёт непроверенные факты из youtube_sources → AI-анализ → verified_facts.
"""

import json, sqlite3, time, sys
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError

DB = Path("/root/herm/health-bot/health.db")
LLM_URL = "http://127.0.0.1:4000/chat/completions"
OLLAMA_KEY = "sk-4e9e073d30502f092ffd3ddfa29e9c46"
BATCH_SIZE = 5  # фактов за один LLM-запрос


def init_db():
    db = sqlite3.connect(str(DB))
    db.execute("""
        CREATE TABLE IF NOT EXISTS verified_facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id INTEGER REFERENCES youtube_sources(id),
            fact TEXT NOT NULL,
            recommendation TEXT,
            original_credibility REAL,
            support_score REAL,
            consensus TEXT,
            critique TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    db.commit()
    db.close()


def get_unverified(limit: int = 30) -> list:
    db = sqlite3.connect(str(DB))
    c = db.cursor()
    c.execute("""
        SELECT ys.id, ys.channel_name, ys.video_url, ys.facts_json, ys.credibility_score
        FROM youtube_sources ys
        WHERE ys.analyzed = 1
          AND ys.id NOT IN (SELECT DISTINCT source_id FROM verified_facts)
        ORDER BY ys.credibility_score DESC
        LIMIT ?
    """, (limit,))
    
    rows = []
    for id_, channel, url, facts_json, cred in c.fetchall():
        facts = json.loads(facts_json)
        rows.append({
            "source_id": id_,
            "channel": channel,
            "url": url,
            "facts": facts,
            "original_cred": cred,
        })
    db.close()
    return rows


def call_llm(prompt: str, max_retries: int = 3) -> str:
    """LiteLLM → gemma4:31b с ретраями."""
    data = json.dumps({
        "model": "openai/gemma4:31b",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 2000,
    }).encode()

    for attempt in range(max_retries):
        try:
            req = Request(LLM_URL, data=data, method="POST")
            req.add_header("Content-Type", "application/json")
            req.add_header("Authorization", f"Bearer {OLLAMA_KEY}")
            
            with urlopen(req, timeout=90) as resp:
                body = json.loads(resp.read())
                return body["choices"][0]["message"]["content"]
        except Exception as e:
            print(f"  LLM retry {attempt+1}/{max_retries}: {e}", file=sys.stderr)
            time.sleep(5)
    
    return ""


def build_batch_prompt(facts_batch: list) -> str:
    """Промпт для батча фактов."""
    items = []
    for item in facts_batch:
        items.append(
            f'ID={item["fact_id"]} | Канал: {item["channel"]}\n'
            f'  Факт: "{item["fact"]}"\n'
            f'  Рекомендация: {item["recommendation"][:100]}\n'
            f'  Исходная credibility: {item["original_cred"]}'
        )
    
    return f"""Ты — научный health-фактчекер. Проанализируй утверждения. Для каждого:

VERDICT:
- SUPPORTED — научный консенсус, есть клинические данные
- REFUTED — противоречит науке или антинаучный миф
- UNCERTAIN — данных недостаточно

support_score: 0.0-1.0 (1.0 = доказано, 0.0 = опровергнуто)
critique: 1 предложение-обоснование

Канал влияет на baseline достоверности:
- Университеты/институты (NIH, Buck, Harvard, Stanford, Mayo, Oxford, Cambridge, Yale, USC, Salk) → высокая
- @DrEricBerg → 0.85
- @eokomarovskiy → 0.8
- @Max_Pogorely → 0.7

{chr(10).join(items)}

Ответь СТРОГО JSON (без markdown):
[{{"fact_id":"ID","verdict":"SUPPORTED|REFUTED|UNCERTAIN","support_score":0.0-1.0,"critique":"..."}}]"""


def parse_json(raw: str) -> list:
    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        lines = [l for l in lines if not l.startswith("```")]
        raw = "\n".join(lines)
    
    try:
        return json.loads(raw)
    except:
        import re
        m = re.search(r'\[.*\]', raw, re.DOTALL)
        return json.loads(m.group()) if m else []


def save_verified(source_id: int, fact: str, recommendation: str,
                  original_cred: float, support_score: float,
                  consensus: str, critique: str):
    db = sqlite3.connect(str(DB))
    db.execute(
        """INSERT INTO verified_facts 
           (source_id, fact, recommendation, original_credibility, support_score, consensus, critique)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (source_id, fact, recommendation, original_cred, support_score, consensus, critique)
    )
    db.commit()
    db.close()


def main():
    init_db()
    
    # Собрать все непроверенные факты
    sources = get_unverified(limit=30)
    
    # Разложить в плоский список фактов
    flat_facts = []
    for src in sources:
        for i, f in enumerate(src["facts"], 1):
            flat_facts.append({
                "fact_id": f"{src['source_id']}/{i}",
                "source_id": src["source_id"],
                "channel": src["channel"],
                "fact": f["fact"],
                "recommendation": f.get("recommendation", ""),
                "original_cred": f.get("credibility", src["original_cred"]),
            })
    
    print(f"🔍 {len(sources)} видео → {len(flat_facts)} фактов\n")
    
    # Батчи по BATCH_SIZE
    stats = {"supported": 0, "refuted": 0, "uncertain": 0, "saved": 0, "errors": 0}
    
    for offset in range(0, len(flat_facts), BATCH_SIZE):
        batch = flat_facts[offset:offset + BATCH_SIZE]
        batch_num = offset // BATCH_SIZE + 1
        total_batches = (len(flat_facts) + BATCH_SIZE - 1) // BATCH_SIZE
        
        print(f"  📦 Батч {batch_num}/{total_batches} ({len(batch)} фактов)...", end=" ", flush=True)
        
        prompt = build_batch_prompt(batch)
        raw = call_llm(prompt)
        
        if not raw:
            print("❌ LLM fail")
            stats["errors"] += len(batch)
            continue
        
        verdicts = parse_json(raw)
        if not verdicts:
            print(f"⚠️ JSON parse fail (raw: {raw[:100]})")
            stats["errors"] += len(batch)
            continue
        
        print(f"✅ {len(verdicts)} вердиктов")
        
        # Сохранить
        fact_index = {f["fact_id"]: f for f in batch}
        for v in verdicts:
            fid = v.get("fact_id", "")
            info = fact_index.get(fid)
            if not info:
                continue
            
            verdict = v.get("verdict", "UNCERTAIN").upper()
            if verdict == "SUPPORTED":
                consensus = "supported"
                stats["supported"] += 1
            elif verdict == "REFUTED":
                consensus = "refuted"
                stats["refuted"] += 1
            else:
                consensus = "uncertain"
                stats["uncertain"] += 1
            
            score = max(0.0, min(1.0, float(v.get("support_score", 0.5))))
            critique = v.get("critique", "")[:500]
            
            save_verified(
                info["source_id"], info["fact"], info["recommendation"],
                info["original_cred"], score, consensus, critique
            )
            stats["saved"] += 1
        
        time.sleep(1)  # Anti rate-limit
    
    print(f"\n{'='*50}")
    print(f"✅ Сохранено: {stats['saved']}")
    print(f"   Подтверждено: {stats['supported']}")
    print(f"   Неопределено: {stats['uncertain']}")
    print(f"   Опровергнуто: {stats['refuted']}")
    print(f"   Ошибок: {stats['errors']}")


if __name__ == "__main__":
    main()
