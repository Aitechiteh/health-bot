# Health Bot — Personal AI Health Assistant

AI-ассистент для долголетия и здоровья. Telegram-бот с AI-чатом, парсер longevity-исследований и автоматическими напоминалками.

## Возможности

### Telegram-бот (@health_alex_bot)
- **💬 NL-чат с AI** — любой вопрос о здоровье → ответ на основе проверенных научных фактов
- **🤖 AI-совет** — персонализированные рекомендации (питание, спорт, бады)
- **📋 План здоровья** — еженедельный план питания и тренировок
- **🛒 Корзина** — список покупок на месяц
- **🔥💊🏋️💤** — трекер привычек, бадов, тренировок и сна

### Longevity-парсер
- 18 источников (Harvard, NAM, LSF, Swiss Campus, Salk, Buck, Lifespan.io, Fight Aging, WHO...)
- RSS + YouTube + X/Twitter мониторинг
- AI-куратор (gemma4:31b): классификация + извлечение ключевых фактов на русском
- Обновление каждые 6 часов

### Напоминалки (CEST)
- 07:00 — утренняя зарядка
- 09:00 — бады с завтраком
- 13:00 — бады после обеда
- 17:00 — зона 2 кардио
- 19:30 — вечерние бады
- 22:00 — подготовка ко сну

## Архитектура

```
health-bot/
├── api.py              # FastAPI backend (:8082)
├── bot.py              # aiogram 3 Telegram-бот
├── reminders.py        # Напоминалки (спорт/бады/сон)
├── longevity_parser.py # Парсер longevity-источников
├── longevity_sources.json # Конфиг 18 источников
├── digest.py           # YouTube → транскрипты → факты
├── fact_checker.py     # Проверка фактов через LLM
├── health_planner.py   # Генератор плана здоровья
├── shopping_list.py    # Генератор корзины покупок
├── pipeline.py         # Оркестратор полного цикла
└── health.db           # SQLite (сессии, факты, планы)
```

## Контекст

- Пользователь: Алекс, 46 лет, 174 см, 74-76 кг
- Цель: долголетие и подвижность
- Часовой пояс: Europe/Berlin (CEST/CET)
- Язык: русский

## Установка

```bash
# Зависимости
pip install fastapi uvicorn aiogram feedparser --break-system-packages

# Переменные окружения (.env)
BOT_TOKEN=your_telegram_bot_token
CHAT_ID=your_chat_id

# Запуск API
uvicorn api:app --host 0.0.0.0 --port 8082

# Запуск бота
python3 bot.py
```

## Лицензия

MIT
