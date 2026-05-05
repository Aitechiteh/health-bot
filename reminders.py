#!/usr/bin/env python3
"""Персональные напоминалки: читает personal_profile из БД и шлёт реальные названия."""

import sys, json, sqlite3
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen

BOT_TOKEN = "8596541755:AAF9G9jv2EShD2bA5z3GDxLcMewy6aHkjio"
CHAT_ID = "167413129"
DB_PATH = Path(__file__).parent / "health.db"


def get_profile():
    """Загрузить personal_profile из БД."""
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    rows = db.execute(
        "SELECT section, priority, item, dosage, timing, reason, category FROM personal_profile ORDER BY section, priority"
    ).fetchall()
    db.close()

    profile = {}
    for r in rows:
        profile.setdefault(r["section"], []).append(dict(r))
    return profile


def pick_items(items: list, timing_keywords: list, category_filter: str = None, priority_max: int = 3) -> list:
    """Выбрать элементы по времени/категории."""
    result = []
    for it in items:
        timing = (it.get("timing") or "").lower()
        cat = (it.get("category") or "").lower()
        # Фильтр по категории
        if category_filter and cat and category_filter.lower() not in cat:
            continue
        # Фильтр по приоритету
        if it["priority"] > priority_max:
            continue
        # Фильтр по времени
        if any(kw in timing for kw in timing_keywords):
            result.append(it)
    return result


def build_supplement_message(supps: list, timing_name: str) -> str:
    """Сформировать сообщение для добавок."""
    if not supps:
        return ""

    lines = [f"💊 <b>{timing_name} — время бадов!</b>\n"]
    for s in supps:
        dose = f" — {s['dosage']}" if s.get("dosage") else ""
        lines.append(f"  • {s['item']}{dose}")
    return "\n".join(lines)


def build_sport_message(sport: list) -> str:
    """Сообщение для спорта."""
    if not sport:
        return ""

    primary = [s for s in sport if s["priority"] == 1]
    secondary = [s for s in sport if s["priority"] == 2]

    lines = ["🏋️ <b>Время тренировки, Алекс!</b>\n"]
    if primary:
        lines.append("<b>Сегодня в фокусе:</b>")
        for s in primary[:3]:
            freq = f" — {s['dosage']}" if s.get("dosage") else ""
            lines.append(f"  • {s['item']}{freq}")
    if secondary:
        lines.append(f"\n<b>Дополнительно:</b>")
        for s in secondary[:2]:
            lines.append(f"  • {s['item']}")

    lines.append(f"\n<i>Минимум 20 минут активности — твой вклад в долголетие!</i>")
    return "\n".join(lines)


def build_sleep_message(sleep: list) -> str:
    """Сообщение для сна."""
    if not sleep:
        return ""

    must = [s for s in sleep if s["priority"] == 1]
    lines = ["💤 <b>Время замедляться — готовься ко сну</b>\n"]
    if must:
        for s in must[:4]:
            lines.append(f"  • {s['item']}")
    lines.append(f"\n<i>Цель: лечь в 22:30, спать 7.5–8.5 ч в прохладе и темноте 🌙</i>")
    return "\n".join(lines)


def send_telegram(text: str):
    """Отправить сообщение в Telegram."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = json.dumps({"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}).encode()
    req = Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read())
            if not body.get("ok"):
                print(f"Telegram error: {body.get('description')}", file=sys.stderr)
                return False
            return True
    except Exception as e:
        print(f"Send error: {e}", file=sys.stderr)
        return False


# === СЛОТЫ НАПОМИНАНИЙ ===
SLOTS = {
    "morning_sport":       {"hour": 7,  "category": "sport"},
    "breakfast_supplements": {"hour": 9,  "category": "morning_supps"},
    "lunch_supplements":     {"hour": 13, "category": "lunch_supps"},
    "evening_supplements":   {"hour": 19, "category": "evening_supps"},
    "sport_reminder":        {"hour": 17, "category": "sport"},
    "sleep_winddown":        {"hour": 22, "category": "sleep"},
}


def main():
    slot = sys.argv[1] if len(sys.argv) > 1 else None

    if slot and slot not in SLOTS:
        print(f"Unknown slot: {slot}. Available: {', '.join(SLOTS.keys())}", file=sys.stderr)
        sys.exit(1)

    if not slot:
        # Автоопределение: какой сейчас час
        now = datetime.now()
        for name, cfg in SLOTS.items():
            if now.hour == cfg["hour"]:
                slot = name
                break
        if not slot:
            print(f"⏭️ No reminder slot for hour {now.hour}")
            return

    cfg = SLOTS[slot]
    profile = get_profile()

    if cfg["category"] == "sport":
        sport = profile.get("sport", [])
        text = build_sport_message(sport)
    elif cfg["category"] == "sleep":
        sleep_items = profile.get("sleep", [])
        text = build_sleep_message(sleep_items)
    elif cfg["category"] == "morning_supps":
        supps = profile.get("supplements", [])
        morning = pick_items(supps, ["утро", "завтрак"], priority_max=2)
        if not morning:
            morning = pick_items(supps, ["утро", "завтрак"], priority_max=3)
        text = build_supplement_message(morning, "Утро")
    elif cfg["category"] == "lunch_supps":
        supps = profile.get("supplements", [])
        lunch = pick_items(supps, ["день", "обед"], priority_max=2)
        if not lunch:
            lunch = pick_items(supps, ["день", "обед"], priority_max=3)
        text = build_supplement_message(lunch, "После обеда")
    elif cfg["category"] == "evening_supps":
        supps = profile.get("supplements", [])
        evening = pick_items(supps, ["вечер", "ужин"], priority_max=2)
        if not evening:
            evening = pick_items(supps, ["вечер", "ужин"], priority_max=3)
        text = build_supplement_message(evening, "Вечер")

    if not text:
        print(f"⏭️ No items for slot '{slot}' — skipping")
        return

    print(f"📤 Sending: {slot}")
    ok = send_telegram(text)
    print("✅ OK" if ok else "❌ FAILED")


if __name__ == "__main__":
    main()
