#!/usr/bin/env python3
"""
🛒 Shopping List Generator — корзина продуктов и бадов на месяц.
Берёт health_plans + verified_facts → список покупок на месяц.
"""

import json, sqlite3, time, sys
from pathlib import Path
from datetime import date, datetime
from urllib.request import Request, urlopen

DB = Path("/root/herm/health-bot/health.db")
LLM_URL = "http://127.0.0.1:4000/chat/completions"
KEY = "sk-4e9e073d30502f092ffd3ddfa29e9c46"


def get_latest_plan() -> dict:
    """Последний health план."""
    db = sqlite3.connect(str(DB))
    c = db.cursor()
    c.execute("""
        SELECT section, content FROM health_plans
        WHERE week_start = (SELECT MAX(week_start) FROM health_plans)
        ORDER BY section
    """)
    plan = {}
    for section, content in c.fetchall():
        plan[section] = json.loads(content)
    db.close()
    return plan


def get_supplement_facts() -> list:
    """Только supported факты про добавки."""
    db = sqlite3.connect(str(DB))
    c = db.cursor()
    c.execute("""
        SELECT vf.fact, vf.recommendation, vf.support_score
        FROM verified_facts vf
        WHERE vf.consensus = 'supported'
          AND (LOWER(vf.fact) LIKE '%добавк%' OR LOWER(vf.fact) LIKE '%витам%'
               OR LOWER(vf.fact) LIKE '%бад%' OR LOWER(vf.fact) LIKE '%магни%'
               OR LOWER(vf.fact) LIKE '%цинк%' OR LOWER(vf.fact) LIKE '%омега%'
               OR LOWER(vf.fact) LIKE '%d3%' OR LOWER(vf.fact) LIKE '%креатин%')
        ORDER BY vf.support_score DESC
        LIMIT 20
    """)
    facts = [{"fact": r[0], "recommendation": r[1], "score": r[2]} for r in c.fetchall()]
    db.close()
    return facts


def call_llm(prompt: str) -> str:
    data = json.dumps({
        "model": "openai/gemma4:31b",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.4,
        "max_tokens": 2500,
    }).encode()
    
    for attempt in range(3):
        try:
            req = Request(LLM_URL, data=data, method="POST")
            req.add_header("Content-Type", "application/json")
            req.add_header("Authorization", f"Bearer {KEY}")
            with urlopen(req, timeout=90) as resp:
                return json.loads(resp.read())["choices"][0]["message"]["content"]
        except Exception as e:
            print(f"  LLM retry {attempt+1}: {e}", file=sys.stderr)
            time.sleep(5)
    return ""


def generate_shopping(plan: dict, supp_facts: list) -> dict:
    """Сгенерировать корзину на месяц."""
    
    plan_text = ""
    for section, data in plan.items():
        if data and "recommendations" in data:
            plan_text += f"\n{section}:\n"
            for rec in data["recommendations"][:5]:
                plan_text += f"  - {rec['item']}\n"
    
    supp_text = "\n".join(
        f"- {f['fact']} (score: {f['score']:.2f}) → {f['recommendation']}"
        for f in supp_facts
    )
    
    prompt = f"""Ты — персональный health-шеф. На основе плана здоровья сформируй корзину покупок на МЕСЯЦ.

Профиль: мужчина 46 лет, 74-76 кг, 174 см, цель — долголетие.

ПЛАН ЗДОРОВЬЯ:
{plan_text}

ФАКТЫ О ДОБАВКАХ:
{supp_text}

Составь СПИСОК ПОКУПОК в 3 категориях:
1. ПРОДУКТЫ: что купить на месяц (конкретные названия + примерное кол-во/кг)
2. БАДЫ: добавки с дозировками (название, форма, сколько упаковок)
3. СПОРТ: инвентарь если нужен (коврик, эспандер, etc)

Учитывай:
- Budget-friendly варианты где возможно
- Где заказать (аптека, маркетплейс, магазин)
- Срок годности скоропортящихся продуктов

Ответь СТРОГО в JSON:
{{
  "month": "{date.today().strftime('%Y-%m')}",
  "categories": {{
    "food": [
      {{"name": "...", "quantity": "2 кг / 4 шт", "reason": "почему это в плане", "approx_cost": "~500₽"}}
    ],
    "supplements": [
      {{"name": "...", "dosage": "400 мг/день", "quantity": "1 упаковка 60 капс", "reason": "...", "approx_cost": "~800₽"}}
    ],
    "sports": [
      {{"name": "...", "reason": "...", "approx_cost": "~1500₽"}}
    ]
  }},
  "total_approx": "~X руб",
  "notes": "советы по закупке"
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
        print(f"  ⚠️ JSON fail: {raw[:200]}", file=sys.stderr)
        return None


def save_shopping_list(data: dict):
    db = sqlite3.connect(str(DB))
    for cat, items in data.get("categories", {}).items():
        db.execute(
            "INSERT INTO shopping_lists (month, category, items_json) VALUES (?, ?, ?)",
            (data["month"], cat, json.dumps(items, ensure_ascii=False))
        )
    db.commit()
    db.close()


def format_shopping_html(data: dict) -> str:
    """HTML для Telegram."""
    emoji = {"food": "🥗", "supplements": "💊", "sports": "🏋️"}
    lines = [
        f"🛒 <b>Корзина здоровья — {data.get('month', 'текущий месяц')}</b>\n",
        "━━━━━━━━━━━"
    ]
    
    for cat, items in data.get("categories", {}).items():
        em = emoji.get(cat, "📦")
        lines.append(f"\n{em} <b>{cat.upper()}</b>")
        for item in items:
            lines.append(f"  • {item['name']}")
            if item.get("quantity"):
                lines.append(f"    📦 {item['quantity']}")
            if item.get("reason"):
                lines.append(f"    💡 {item['reason'][:100]}")
            if item.get("approx_cost"):
                lines.append(f"    💰 {item['approx_cost']}")
    
    lines.append(f"\n━━━━━━━━━━━")
    lines.append(f"💰 <b>Примерный бюджет:</b> {data.get('total_approx', '')}")
    if data.get("notes"):
        lines.append(f"📝 <i>{data['notes'][:200]}</i>")
    
    return "\n".join(lines)


def main():
    print("🛒 Shopping List Generator\n")
    
    print("📋 Загружаем план здоровья...")
    plan = get_latest_plan()
    if not plan:
        print("❌ Нет health-плана. Сначала запусти health_planner.py")
        return
    print(f"   Найдены секции: {list(plan.keys())}")
    
    print("💊 Загружаем факты о добавках...")
    supp_facts = get_supplement_facts()
    print(f"   Найдено: {len(supp_facts)} фактов")
    
    print("🧠 Генерируем корзину...")
    shopping = generate_shopping(plan, supp_facts)
    
    if shopping:
        save_shopping_list(shopping)
        html = format_shopping_html(shopping)
        print("\n" + "="*50)
        print(html)
    else:
        print("❌ Не удалось сгенерировать")


if __name__ == "__main__":
    main()
