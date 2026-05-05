#!/usr/bin/env python3
"""Напоминалки для @health_alex_bot: спорт, бады, сон."""

import sys, json
from datetime import datetime
from urllib.request import Request, urlopen

BOT_TOKEN = "8596541755:AAF9G9jv2EShD2bA5z3GDxLcMewy6aHkjio"
CHAT_ID = "167413129"

REMINDERS = {
    "morning_sport": {
        "text": (
            "🏋️ <b>Доброе утро, Алекс!</b>\n\n"
            "Время для утренней зарядки:\n"
            "• 5 минут растяжки\n"
            "• 20 отжиманий / 30 приседаний\n"
            "• Контрастный душ 🚿\n\n"
            "<i>Зона 2 кардио — вечером!</i>"
        ),
        "time": "07:00",
    },
    "breakfast_supplements": {
        "text": (
            "💊 <b>Утро — время бадов</b>\n\n"
            "Прими с завтраком:\n"
            "• Витамин D3 + K2\n"
            "• Магний цитрат\n"
            "• Омега-3 (EPA/DHA)\n\n"
            "<i>Запивай водой, не чаем!</i>"
        ),
        "time": "09:00",
    },
    "lunch_supplements": {
        "text": (
            "💊 <b>После обеда</b>\n\n"
            "Прими с едой:\n"
            "• Витамин C 500 мг\n"
            "• Цинк (если сегодня нет мяса)\n\n"
            "<i>Помни про белок 1.6 г/кг в день!</i>"
        ),
        "time": "13:00",
    },
    "evening_supplements": {
        "text": (
            "💊 <b>Вечерний пул бадов</b>\n\n"
            "После ужина:\n"
            "• Магний глицинат (для сна)\n"
            "• Ашваганда / L-теанин (по желанию)\n\n"
            "<i>Не пей магний с кальцием вместе!</i>"
        ),
        "time": "19:30",
    },
    "sleep_winddown": {
        "text": (
            "💤 <b>Время замедляться</b>\n\n"
            "Подготовка ко сну:\n"
            "• Выключи экраны\n"
            "• Проветри спальню (18–20°C)\n"
            "• 5–10 минут дыхания 4–7–8\n\n"
            "<i>Цель: лечь в 22:45, спать 7.5–8.5 ч</i>"
        ),
        "time": "22:00",
    },
    "sport_reminder": {
        "text": (
            "🏃 <b>Время для зоны 2!</b>\n\n"
            "40–60 минут:\n"
            "• Ходьба в горку / эллипс\n"
            "• Пульс ~130–140 (60–70% макс)\n"
            "• Или велосипед в лёгком темпе\n\n"
            "<i>Можешь совместить с подкастом 🎧</i>"
        ),
        "time": "17:00",
    },
}


def send_telegram(text: str):
    """Отправить сообщение в Telegram."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = json.dumps({
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
    }).encode()

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


def main():
    now = datetime.now()
    current_time = now.strftime("%H:%M")

    # Если передан аргумент — отправить конкретное напоминание
    if len(sys.argv) > 1:
        key = sys.argv[1]
        if key in REMINDERS:
            print(f"Sending: {key}")
            ok = send_telegram(REMINDERS[key]["text"])
            print("OK" if ok else "FAILED")
        else:
            print(f"Unknown reminder: {key}", file=sys.stderr)
            print(f"Available: {', '.join(REMINDERS.keys())}")
            sys.exit(1)
        return

    # Без аргументов: проверить, подходит ли текущее время
    for key, rem in REMINDERS.items():
        if current_time == rem["time"]:
            print(f"Sending: {key}")
            ok = send_telegram(rem["text"])
            print("OK" if ok else "FAILED")


if __name__ == "__main__":
    main()
