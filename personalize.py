#!/usr/bin/env python3
"""
Personalize — AI-аналитик на основе ВСЕХ данных health-хаба.
Генерирует персональный health-профиль Алекса: бады, питание, спорт, сон.
Сохраняет в БД и обновляет reminders/bot.
"""

import sys, json, time
from datetime import datetime, date
from urllib.request import Request, urlopen
from pathlib import Path
import sqlite3, re

DB_PATH = Path(__file__).parent / "health.db"
LITELLM_KEY = "sk-4e9e073d30502f092ffd3ddfa29e9c46"
LLM_MODEL = "gemma4:31b"
LLM_TIMEOUT = 180

USER_PROFILE = {
    "name": "Алекс",
    "age": 46,
    "weight_kg": "74-76",
    "height_cm": 174,
    "location": "Германия",
    "timezone": "Europe/Berlin",
    "goal": "долголетие и подвижность (healthspan)",
    "language": "русский",
}


def get_db():
    return sqlite3.connect(str(DB_PATH))


def init_schema():
    db = get_db()
    db.execute("""
        CREATE TABLE IF NOT EXISTS personal_profile (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            section TEXT NOT NULL,          -- supplements, nutrition, sport, sleep
            priority INTEGER DEFAULT 0,    -- 1 = must do, 2 = recommended, 3 = optional
            item TEXT NOT NULL,             -- e.g. "Витамин D3 4000 IU"
            dosage TEXT,                    -- дозировка
            timing TEXT,                    -- когда принимать
            reason TEXT,                    -- почему (со ссылкой на источник)
            source_id TEXT,                 -- ID источника (из longevity_sources / verified_facts)
            category TEXT,                  -- подкатегория
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS weekly_schedule (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            day_of_week INTEGER NOT NULL,    -- 0=Mon ... 6=Sun
            time_of_day TEXT,                -- HH:MM
            activity TEXT NOT NULL,           -- что делать
            category TEXT,                   -- supplements, sport, nutrition, sleep
            duration_min INTEGER,            -- продолжительность в минутах
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    db.commit()
    db.close()


def gather_context() -> dict:
    """Собрать все данные для анализа."""
    db = get_db()
    db.row_factory = sqlite3.Row

    # 1. Проверенные факты (top 25 по score)
    verified = []
    for r in db.execute("""
        SELECT fact, recommendation, support_score 
        FROM verified_facts 
        WHERE consensus='supported' 
        ORDER BY support_score DESC LIMIT 25
    """):
        verified.append({
            "fact": r["fact"],
            "recommendation": r["recommendation"],
            "score": round(r["support_score"], 2),
        })

    # 2. Longevity-новости с высокой релевантностью
    longevity = []
    for r in db.execute("""
        SELECT title, extracted_fact, relevance_score, category, source_name
        FROM longevity_news 
        WHERE curated=1 AND relevance_score >= 6
        AND category IN ('supplements','nutrition','exercise','sleep','biomarkers','drugs')
        ORDER BY relevance_score DESC LIMIT 15
    """):
        longevity.append({
            "title": r["title"],
            "fact": r["extracted_fact"],
            "score": r["relevance_score"],
            "category": r["category"],
            "source": r["source_name"],
        })

    # 3. Текущий план здоровья
    plan = {}
    for r in db.execute("""
        SELECT section, content FROM health_plans 
        WHERE week_start=(SELECT MAX(week_start) FROM health_plans)
    """):
        try:
            plan[r["section"]] = json.loads(r["content"])
        except:
            plan[r["section"]] = r["content"]

    db.close()

    return {
        "verified_facts": verified,
        "longevity_news": longevity,
        "health_plan": plan,
    }


def call_llm(prompt: str) -> dict:
    """Вызов LLM через LiteLLM."""
    data = json.dumps({
        "model": LLM_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.4, "max_tokens": 3000,
    }).encode()

    req = Request("http://127.0.0.1:4000/chat/completions", data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {LITELLM_KEY}")

    with urlopen(req, timeout=LLM_TIMEOUT) as resp:
        body = json.loads(resp.read())
        raw = body["choices"][0]["message"]["content"]

    # Извлечь JSON массив из ответа
    raw = raw.strip()
    # Убрать markdown обёртки
    if raw.startswith("```"):
        raw = re.sub(r'^```\w*\n', '', raw)
        raw = re.sub(r'\n```$', '', raw)
    
    # Найти JSON массив (не объект)
    m = re.search(r'\[[\s\S]*\]', raw)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    
    # Fallback: попробовать весь ответ как JSON
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    
    # Last resort: найти любой JSON
    m = re.search(r'\{[\s\S]*\}', raw)
    if m:
        return json.loads(m.group(0))
    
    print(f"Cannot parse JSON from: {raw[:200]}", file=sys.stderr)
    return []


def analyze_supplements(context: dict) -> list:
    """AI-анализ бадов."""
    verified_text = "\n".join(
        f"- {f['fact']} (score: {f['score']}) → {f['recommendation']}"
        for f in context["verified_facts"]
        if any(k in (f["fact"] + f["recommendation"]).lower() 
               for k in ["витамин", "supplement", "добавк", "magnesium", "d3", "omega", "цинк", "zinc", "магний", "дозиров"])
    )
    
    news_text = "\n".join(
        f"- [{n['category']}] {n['fact']}"
        for n in context["longevity_news"]
    )

    prompt = f"""Ты — AI-аналитик долголетия. Составь ПЕРСОНАЛЬНЫЙ протокол бадов для:

{json.dumps(USER_PROFILE, ensure_ascii=False, indent=2)}

НАУЧНЫЕ ДАННЫЕ:
=== ПРОВЕРЕННЫЕ ФАКТЫ ===
{verified_text[:2500]}

=== СВЕЖИЕ LONGEVITY-НОВОСТИ ===
{news_text[:2500]}

Верни JSON-массив бадов. Каждый элемент — объект:
{{
  "item": "Название бада и дозировка (e.g. Витамин D3 4000 IU)",
  "priority": 1-3 (1=must, 2=recommended, 3=optional),
  "timing": "когда принимать (утро/день/вечер/с едой)",
  "reason": "почему — 1 предложение со ссылкой на исследование",
  "category": "vitamin / mineral / hormone / nootropic / longevity"
}}

Дай 10-15 конкретных бадов, отсортированных по priority.
Учти: Алекс в Германии → дефицит D3. Цель — долголетие, не спорт. Бюджет не важен — предлагай лучшее.

ОТВЕТ — ТОЛЬКО JSON МАССИВ. Никаких пояснений, markdown-блоков или текста до/после JSON.:
[{...}, {...}]"""

    try:
        result = call_llm(prompt)
        if isinstance(result, dict):
            result = result.get("supplements", result.get("data", []))
        return result if isinstance(result, list) else []
    except Exception as e:
        print(f"Supplements analysis error: {e}", file=sys.stderr)
        return []


def analyze_nutrition(context: dict) -> list:
    """AI-анализ питания."""
    verified_text = "\n".join(
        f"- {f['fact']} → {f['recommendation']}"
        for f in context["verified_facts"]
        if any(k in (f["fact"] + f["recommendation"]).lower() 
               for k in ["питани", "белок", "углевод", "жир", "nutrition", "protein", "голод", "fasting", "интервал"])
    )

    prompt = f"""Ты — AI-диетолог долголетия. Составь ПРОТОКОЛ ПИТАНИЯ для:

{json.dumps(USER_PROFILE, ensure_ascii=False, indent=2)}

НАУЧНЫЕ ДАННЫЕ:
{verified_text[:2000]}

Верни JSON-массив принципов питания. Каждый:
{{
  "item": "Конкретный принцип (e.g. Интервальное голодание 16:8)",
  "priority": 1-3,
  "detail": "как внедрить — конкретные шаги",
  "reason": "почему — научное обоснование",
  "category": "timing / macros / foods / habits"
}}

Дай 8-12 принципов. Учти: Германия → доступ к качественным продуктам, DM для бадов.

ОТВЕТ — ТОЛЬКО JSON МАССИВ. Никаких пояснений, markdown-блоков или текста до/после JSON.:
[{...}, {...}]"""

    try:
        result = call_llm(prompt)
        if isinstance(result, dict):
            result = result.get("nutrition", result.get("data", []))
        return result if isinstance(result, list) else []
    except Exception as e:
        print(f"Nutrition analysis error: {e}", file=sys.stderr)
        return []


def analyze_sport(context: dict) -> list:
    """AI-анализ спорта: зона 2 + силовые + мобильность."""
    verified_text = "\n".join(
        f"- {f['fact']} → {f['recommendation']}"
        for f in context["verified_facts"]
        if any(k in (f["fact"] + f["recommendation"]).lower() 
               for k in ["упражн", "спорт", "тренир", "exercise", "сил", "zone", "кардио", "мобил", "vo2max", "мышц"])
    )

    prompt = f"""Ты — AI-тренер долголетия. Составь ПРОТОКОЛ ТРЕНИРОВОК для:

{json.dumps(USER_PROFILE, ensure_ascii=False, indent=2)}

НАУЧНЫЕ ДАННЫЕ:
{verified_text[:2000]}

Верни JSON-массив тренировочных принципов. Каждый:
{{
  "item": "Тип тренировки (e.g. Зона 2 кардио 45-60 мин)",
  "priority": 1-3,
  "frequency": "сколько раз в неделю",
  "detail": "конкретные упражнения / как делать",
  "reason": "почему — научное обоснование для долголетия",
  "category": "zone2 / strength / mobility / hiit / vo2max"
}}

Дай 8-12 пунктов. Обязательно включи:
- Зона 2 кардио (основа longevity)
- Силовые тренировки (2-3 раза/нед, базовые упражнения)
- Мобильность/растяжка
- VO2max работа (раз в неделю)

ОТВЕТ — ТОЛЬКО JSON МАССИВ. Никаких пояснений, markdown-блоков или текста до/после JSON.:
[{...}, {...}]"""

    try:
        result = call_llm(prompt)
        if isinstance(result, dict):
            result = result.get("sport", result.get("exercise", result.get("data", [])))
        return result if isinstance(result, list) else []
    except Exception as e:
        print(f"Sport analysis error: {e}", file=sys.stderr)
        return []


def analyze_sleep(context: dict) -> list:
    """AI-анализ сна."""
    verified_text = "\n".join(
        f"- {f['fact']} → {f['recommendation']}"
        for f in context["verified_facts"]
        if any(k in (f["fact"] + f["recommendation"]).lower() 
               for k in ["сон", "sleep", "циркад", "мелатон", "вечер", "экран", "гигиен"])
    )

    news_text = "\n".join(
        f"- {n['fact']}" for n in context["longevity_news"] if n["category"] == "sleep"
    )

    prompt = f"""Ты — AI-специалист по сну для долголетия. Составь ПРОТОКОЛ СНА для:

{json.dumps(USER_PROFILE, ensure_ascii=False, indent=2)}

НАУЧНЫЕ ДАННЫЕ:
{verified_text[:1500]}
{news_text[:1000]}

Верни JSON-массив принципов сна. Каждый:
{{
  "item": "Конкретный принцип (e.g. Ложиться в 22:45)",
  "priority": 1-3,
  "detail": "как внедрить",
  "reason": "почему — наука",
  "category": "timing / environment / habits / supplements"
}}

Дай 8-10 пунктов. Фокус: долголетие, восстановление, когнитивное здоровье.

ОТВЕТ — ТОЛЬКО JSON МАССИВ. Никаких пояснений, markdown-блоков или текста до/после JSON.:
[{...}, {...}]"""

    try:
        result = call_llm(prompt)
        if isinstance(result, dict):
            result = result.get("sleep", result.get("data", []))
        return result if isinstance(result, list) else []
    except Exception as e:
        print(f"Sleep analysis error: {e}", file=sys.stderr)
        return []


def save_profile(section: str, items: list):
    """Сохранить персональные рекомендации в БД."""
    db = get_db()
    # Удалить старые записи для этой секции
    db.execute("DELETE FROM personal_profile WHERE section = ?", (section,))
    
    for i, item in enumerate(items):
        db.execute("""
            INSERT INTO personal_profile 
            (section, priority, item, dosage, timing, reason, source_id, category)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            section,
            item.get("priority", 2),
            item.get("item", ""),
            item.get("dosage", item.get("frequency", "")),
            item.get("timing", item.get("time", "")),
            item.get("reason", item.get("detail", "")),
            item.get("source_id", ""),
            item.get("category", ""),
        ))
    
    db.commit()
    db.close()
    print(f"  ✓ Saved {len(items)} {section} items")


def generate_weekly_schedule():
    """Создать недельное расписание на основе personal_profile."""
    db = get_db()
    db.row_factory = sqlite3.Row
    
    # Удалить старый график
    db.execute("DELETE FROM weekly_schedule")
    
    items = db.execute("""
        SELECT * FROM personal_profile ORDER BY 
            CASE section WHEN 'supplements' THEN 1 WHEN 'sleep' THEN 2 
                         WHEN 'nutrition' THEN 3 WHEN 'sport' THEN 4 END,
            priority
    """).fetchall()
    
    schedule = []
    
    for item in items:
        section = item["section"]
        name = item["item"]
        timing = item["timing"] or ""

        if section == "supplements":
            # Распределяем по дням
            for day in range(7):
                hour = None
                if "утро" in (timing or "").lower() or "завтрак" in (timing or "").lower():
                    hour = "08:00"
                elif "день" in (timing or "").lower() or "обед" in (timing or "").lower():
                    hour = "13:00"
                elif "вечер" in (timing or "").lower() or "ужин" in (timing or "").lower():
                    hour = "19:00"
                
                if hour:
                    schedule.append((day, hour, f"💊 {name}", "supplements", 1))

        elif section == "sport":
            # Распределяем по дням на основе текста (ищем частоту в item/reason)
            freq_text = (item["dosage"] or item["reason"] or item["item"] or "")
            days_per_week = 3  # default
            if "раз" in str(freq_text):
                nums = re.findall(r'(\d+)', str(freq_text))
                if nums:
                    days_per_week = min(int(nums[0]), 7)
            
            for day in range(0, 7, max(1, 7 // days_per_week)):
                schedule.append((day, "07:00", f"🏋️ {name}", "sport", 45))

        elif section == "sleep":
            for day in range(7):
                schedule.append((day, "22:00", f"💤 {name}", "sleep", 5))

        elif section == "nutrition":
            for day in [0, 2, 4]:  # MWF reminders
                schedule.append((day, "09:00", f"🥗 {name}", "nutrition", 5))

    # Сохранить
    for day, time_of_day, activity, category, duration in schedule:
        db.execute("""
            INSERT INTO weekly_schedule (day_of_week, time_of_day, activity, category, duration_min)
            VALUES (?, ?, ?, ?, ?)
        """, (day, time_of_day, activity, category, duration))
    
    db.commit()
    db.close()
    print(f"  ✓ Weekly schedule: {len(schedule)} events")


def main():
    print("=" * 60)
    print("PERSONALIZE — AI-аналитик health-хаба")
    print(f"User: {USER_PROFILE['name']}, {USER_PROFILE['age']} лет, цель: {USER_PROFILE['goal']}")
    print("=" * 60)

    init_schema()

    # Шаг 1: собрать все данные
    print("\n📊 Gathering all data...")
    context = gather_context()
    print(f"  Verified facts: {len(context['verified_facts'])}")
    print(f"  Longevity news: {len(context['longevity_news'])}")
    print(f"  Health plan sections: {list(context['health_plan'].keys())}")

    # Шаг 2: AI-анализ по каждой категории
    print("\n🔬 AI Analysis:")
    
    print("\n  💊 Supplements...")
    supps = analyze_supplements(context)
    save_profile("supplements", supps)

    print("\n  🥗 Nutrition...")
    nutr = analyze_nutrition(context)
    save_profile("nutrition", nutr)

    print("\n  🏋️ Sport & Exercise...")
    sport = analyze_sport(context)
    save_profile("sport", sport)

    print("\n  💤 Sleep...")
    sleep = analyze_sleep(context)
    save_profile("sleep", sleep)

    # Шаг 3: сгенерировать недельное расписание
    print("\n📅 Generating weekly schedule...")
    generate_weekly_schedule()

    # Шаг 4: показать сводку
    db = get_db()
    total_items = db.execute("SELECT COUNT(*) FROM personal_profile").fetchone()[0]
    total_schedule = db.execute("SELECT COUNT(*) FROM weekly_schedule").fetchone()[0]
    db.close()

    print("\n" + "=" * 60)
    print(f"✅ DONE: {total_items} personalized items, {total_schedule} weekly events")
    print("=" * 60)


if __name__ == "__main__":
    main()
