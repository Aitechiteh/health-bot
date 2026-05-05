#!/usr/bin/env python3
"""
📋 Health Planner — персональный план здоровья на основе проверенных фактов.
Берёт supported факты → формирует план: питание, бады, спорт, режим, сон.
"""

import json, sqlite3, time, sys
from pathlib import Path
from datetime import date
from urllib.request import Request, urlopen

DB = Path("/root/herm/health-bot/health.db")
LLM_URL = "http://127.0.0.1:4000/chat/completions"
KEY = "sk-4e9e073d30502f092ffd3ddfa29e9c46"

USER_PROFILE = """
Профиль:
- Возраст: 46 лет
- Вес: 74-76 кг
- Рост: 174 см
- Цель: долголетие, подвижность, anti-aging
- Интересы: биохакинг, питание, фитнес, предотвращение возрастных заболеваний
"""


def init_db():
    db = sqlite3.connect(str(DB))
    db.executescript("""
        CREATE TABLE IF NOT EXISTS health_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            week_start TEXT NOT NULL,
            section TEXT NOT NULL,       -- nutrition, supplements, sport, habits
            content TEXT NOT NULL,        -- HTML/Markdown рекомендации
            source_facts TEXT,            -- JSON: [fact_id, ...]
            generated_at TEXT DEFAULT (datetime('now'))
        );
        
        CREATE TABLE IF NOT EXISTS shopping_lists (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            month TEXT NOT NULL,          -- YYYY-MM
            category TEXT NOT NULL,       -- food, supplements, sports
            items_json TEXT NOT NULL,     -- JSON: [{name, quantity, reason, ...}]
            generated_at TEXT DEFAULT (datetime('now'))
        );
        
        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT DEFAULT 'alex',
            category TEXT NOT NULL,       -- sport, supplement, habit, shopping
            message TEXT NOT NULL,
            time_of_day TEXT NOT NULL,    -- HH:MM
            days TEXT NOT NULL,           -- 'mon,wed,fri' or 'daily'
            active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now'))
        );
    """)
    db.commit()
    db.close()


def get_supported_facts(limit: int = 30) -> list:
    """Только supported/uncertain факты с высоким support_score."""
    db = sqlite3.connect(str(DB))
    c = db.cursor()
    c.execute("""
        SELECT vf.fact, vf.recommendation, vf.support_score, vf.consensus, vf.critique,
               ys.channel_name, vf.source_id
        FROM verified_facts vf
        JOIN youtube_sources ys ON vf.source_id = ys.id
        WHERE vf.consensus IN ('supported', 'uncertain')
        ORDER BY vf.support_score DESC
        LIMIT ?
    """, (limit,))
    facts = [{
        "fact": r[0], "recommendation": r[1], "support_score": r[2],
        "consensus": r[3], "critique": r[4], "channel": r[5], "source_id": r[6],
    } for r in c.fetchall()]
    db.close()
    return facts


def call_llm(prompt: str) -> str:
    data = json.dumps({
        "model": "openai/gemma4:31b",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.5,
        "max_tokens": 3000,
    }).encode()
    
    for attempt in range(3):
        try:
            req = Request(LLM_URL, data=data, method="POST")
            req.add_header("Content-Type", "application/json")
            req.add_header("Authorization", f"Bearer {KEY}")
            with urlopen(req, timeout=120) as resp:
                return json.loads(resp.read())["choices"][0]["message"]["content"]
        except Exception as e:
            print(f"  LLM retry {attempt+1}: {e}", file=sys.stderr)
            time.sleep(5)
    return ""


def generate_plan_section(section: str, facts: list, previous_plan: dict = None) -> dict:
    """Сгенерировать одну секцию плана через LLM."""
    
    section_prompts = {
        "nutrition": """
Сформируй план питания на неделю для 46-летнего мужчины (174 см, 74-76 кг) с целью долголетия.
Основа — проверенные научные факты ниже. Дай:
- Конкретные продукты и блюда на каждый приём пищи
- Что исключить или ограничить
- Калорийность и макросы ориентировочно
- Интервальное голодание (если поддерживается фактами)
""",
        "supplements": """
Составь план приёма биодобавок на неделю для male 46 лет, цель — longevity и anti-aging.
Для каждой добавки:
- Название, дозировка, время приёма (утро/день/вечер)
- Обоснование из фактов
- Возможные противопоказания
- Приоритет: обязательные / опциональные
""",
        "sport": """
Составь план физической активности на неделю для 46-летнего мужчины (вес 74-76 кг, цель — подвижность и долголетие):
- Типы тренировок: кардио, силовые, мобильность/гибкость
- Интенсивность и длительность
- Дни отдыха
- Конкретные упражнения
- Учёт возрастных рисков (суставы, сердце)
""",
        "habits": """
Сформулируй 5-7 ежедневных микро-привычек для longevity на основе фактов.
Каждая:
- Конкретное действие (2-5 минут)
- Время дня
- Научное обоснование из фактов
- Как отслеживать
"""
    }
    
    facts_text = "\n".join(
        f"[f{f['source_id']}] {f['fact']} (score: {f['support_score']:.2f}, канал: {f['channel']})"
        for f in facts
    )
    
    previous = ""
    if previous_plan:
        previous = f"\nУже запланировано в других секциях (не дублируй):\n{json.dumps(previous_plan, ensure_ascii=False, indent=2)}"
    
    prompt = f"""{section_prompts.get(section, section_prompts['nutrition'])}

{USER_PROFILE}

ПРОВЕРЕННЫЕ ФАКТЫ (только supported/uncertain с высоким рейтингом):
{facts_text}
{previous}

Ответь СТРОГО в JSON:
{{
  "section": "{section}",
  "recommendations": [
    {{"item": "конкретная рекомендация", "reason": "обоснование из фактов", "source_fact_ids": [f123], "priority": "high|medium|low"}}
  ],
  "weekly_schedule": "краткий план по дням" or null,
  "summary": "1-2 предложения резюме"
}}"""
    
    raw = call_llm(prompt)
    if not raw:
        return None
    
    raw = raw.strip()
    if raw.startswith("```"):
        lines = [l for l in raw.split("\n") if not l.startswith("```")]
        raw = "\n".join(lines)
    
    try:
        return json.loads(raw)
    except:
        print(f"  ⚠️ JSON parse fail for {section}, raw: {raw[:200]}", file=sys.stderr)
        return None


def save_plan(week_start: str, section: str, plan_data: dict):
    db = sqlite3.connect(str(DB))
    db.execute(
        "INSERT INTO health_plans (week_start, section, content, source_facts) VALUES (?, ?, ?, ?)",
        (week_start, section, json.dumps(plan_data, ensure_ascii=False),
         json.dumps([r.get("source_fact_ids", []) for r in plan_data.get("recommendations", [])]))
    )
    db.commit()
    db.close()


def get_shopping_list(plan: dict) -> list:
    """Из плана сформировать список покупок."""
    items = set()
    for section, data in plan.items():
        if not data:
            continue
        for rec in data.get("recommendations", []):
            item = rec.get("item", "")
            # Вытащить продукты/добавки
            words = item.lower()
            if any(kw in words for kw in ["продукт", "еда", "яйц", "овощ", "фрук", "мяс", "рыб", "орех", "масл"]):
                items.add(("food", item))
            elif any(kw in words for kw in ["добавк", "витам", "бад", "магни", "цинк", "омега", "d3", "креатин"]):
                items.add(("supplement", item))
    
    return [{"category": cat, "name": name} for cat, name in items]


def format_plan_html(plan: dict) -> str:
    """Сформировать HTML для Telegram."""
    today = date.today().strftime("%d.%m.%Y")
    week = date.today().strftime("%Y-W%W")
    
    html = [f"📋 <b>Health Plan — неделя {week} ({today})</b>\n"]
    
    emoji = {"nutrition": "🥗", "supplements": "💊", "sport": "🏋️", "habits": "🧘"}
    
    for section, data in plan.items():
        if not data:
            continue
        em = emoji.get(section, "📌")
        html.append(f"\n{em} <b>{section.upper()}</b>")
        html.append(data.get("summary", ""))
        
        for rec in data.get("recommendations", [])[:5]:
            prio = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(rec.get("priority", "medium"), "")
            html.append(f"  {prio} <i>{rec['item']}</i>")
            if rec.get("reason"):
                html.append(f"    → {rec['reason'][:120]}")
    
    html.append(f"\n━━━━━━━━━━━\n🔬 <i>На основе проверенных научных фактов</i>")
    return "\n".join(html)


def main():
    init_db()
    
    facts = get_supported_facts(limit=20)
    if not facts:
        print("❌ Нет проверенных фактов. Сначала запусти fact_checker.py")
        return
    
    print(f"📊 {len(facts)} фактов для планирования\n")
    
    today_date = date.today()
    week_start = today_date.strftime("%Y-%m-%d")
    
    sections = ["nutrition", "sport"]  # Самые важные секции
    plan = {}
    
    for section in sections:
        print(f"  🧠 {section}...", end=" ", flush=True)
        result = generate_plan_section(section, facts, plan)
        
        if result:
            plan[section] = result
            save_plan(week_start, section, result)
            print(f"✅ {len(result.get('recommendations', []))} рекомендаций")
        else:
            print("❌")
    
    if plan:
        html = format_plan_html(plan)
        print("\n" + "="*50)
        print(html)
        
        plan_file = Path("/root/herm/health-bot/latest_plan.html")
        plan_file.write_text(html)
        print(f"\n💾 План сохранён: {plan_file}")
    else:
        print("❌ Не удалось сгенерировать план")


if __name__ == "__main__":
    main()
