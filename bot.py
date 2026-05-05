#!/usr/bin/env python3
"""💪 Health Bot — персональный health-ассистент Алекса."""

import asyncio
import logging
import os
import re
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

import aiohttp
from aiogram import Bot, Dispatcher, F, types
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.filters import Command

# === Настройки ===
BOT_TOKEN = os.getenv("BOT_TOKEN", "8596541755:AAF9G9jv2EShD2bA5z3GDxLcMewy6aHkjio")
API_URL = os.getenv("API_URL", "http://127.0.0.1:8082")
USER_ID = "alex"  # фиксированный user_id для Алекса

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("health_bot")

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()


# ============================================================
# 🎛️  Клавиатуры
# ============================================================

def main_kb():
    """Главная reply-клавиатура."""
    b = ReplyKeyboardBuilder()
    for label in ["🔥 Привычки", "💊 Добавки", "🏋️ Тренировка", "💤 Сон", "🤖 AI-совет", "📊 Статистика", "📋 План", "🛒 Корзина"]:
        b.button(text=label)
    b.adjust(2, 2, 2, 2)
    return b.as_markup(resize_keyboard=True)


def habits_inline_kb(habits: list) -> types.InlineKeyboardMarkup:
    """Инлайн-клавиатура для привычек: отметить сделанной/отменить."""
    b = InlineKeyboardBuilder()
    for h in habits:
        done = h.get("done", 0)
        emoji = "✅" if done else "⬜️"
        label = f"{emoji} {h['name']} ({h.get('category', 'общее')})"
        b.button(
            text=label,
            callback_data=f"habit_toggle:{h['id']}:{1 - done}",
        )
    b.adjust(1)
    return b.as_markup()


def supplements_inline_kb(supplements: list) -> types.InlineKeyboardMarkup:
    """Инлайн-клавиатура для добавок: отметить принятой/отменить."""
    b = InlineKeyboardBuilder()
    for s in supplements:
        taken = s.get("taken", 0)
        emoji = "💊" if taken else "⬜️"
        label = f"{emoji} {s['name']} ({s.get('dosage', '')}) [{s.get('time_of_day', '')}]"
        b.button(
            text=label,
            callback_data=f"supp_toggle:{s['id']}:{1 - taken}",
        )
    b.adjust(1)
    return b.as_markup()


def quick_actions_kb() -> types.InlineKeyboardMarkup:
    """Инлайн-клавиатура быстрых действий."""
    b = InlineKeyboardBuilder()
    b.button(text="🔥 Привычки", callback_data="cmd:habits")
    b.button(text="💊 Добавки", callback_data="cmd:supplements")
    b.button(text="📊 Статистика", callback_data="cmd:stats")
    b.button(text="🤖 Рекомендация", callback_data="cmd:recommend")
    b.adjust(2, 2)
    return b.as_markup()


# ============================================================
# 🌐  API-хелперы
# ============================================================

async def api_get(path: str) -> dict | None:
    """GET-запрос к health API."""
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(
                f"{API_URL}{path}",
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 200:
                    log.error("API GET %s → status=%s", path, resp.status)
                    return None
                return await resp.json()
    except Exception:
        log.exception("API GET %s error", path)
        return None


async def api_post(path: str, body: dict) -> dict | None:
    """POST-запрос к health API."""
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(
                f"{API_URL}{path}",
                json=body,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 200:
                    log.error("API POST %s → status=%s body=%s", path, resp.status, str(await resp.text())[:200])
                    return None
                return await resp.json()
    except Exception:
        log.exception("API POST %s error", path)
        return None


async def api_patch(path: str, body: dict) -> dict | None:
    """PATCH-запрос к health API."""
    try:
        async with aiohttp.ClientSession() as s:
            async with s.patch(
                f"{API_URL}{path}",
                json=body,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 200:
                    log.error("API PATCH %s → status=%s", path, resp.status)
                    return None
                return await resp.json()
    except Exception:
        log.exception("API PATCH %s error", path)
        return None


# ============================================================
# 📋  Команды
# ============================================================

@dp.message(Command("start"))
async def start(msg: types.Message):
    """Приветствие."""
    await msg.answer(
        "💪 <b>Привет, Алекс!</b> Я твой персональный health-ассистент с AI-мозгами.\n\n"
        "<b>Что я умею:</b>\n"
        "🔥 <b>Привычки</b> — список и отметки на сегодня\n"
        "💊 <b>Добавки</b> — трекинг приёма\n"
        "🏋️ <b>Тренировка</b> — запись тренировок\n"
        "💤 <b>Сон</b> — логирование сна\n"
        "🤖 <b>AI-совет</b> — персональные рекомендации на основе 120+ научных фактов\n"
        "📊 <b>Статистика</b> — стрик, % выполнения\n"
        "📋 <b>План</b> — питание + спорт на неделю\n"
        "🛒 <b>Корзина</b> — список покупок на месяц\n"
        "💬 <b>Чат</b> — просто напиши вопрос, я отвечу!\n\n"
        "<i>Нажми кнопку или задай вопрос — я на связи 24/7!</i>",
        reply_markup=main_kb(),
    )


@dp.message(Command("habits"))
@dp.message(F.text == "🔥 Привычки")
async def habits_cmd(msg: types.Message):
    """Показать привычки на сегодня."""
    data = await api_get(f"/habits/{USER_ID}")
    if not data:
        await msg.answer("😔 Не удалось загрузить привычки. Попробуй позже.", reply_markup=main_kb())
        return

    habits = data.get("habits", [])
    if not habits:
        await msg.answer(
            "📭 На сегодня привычек пока нет.\n"
            "Добавь новую: <code>/add_habit [название] [категория]</code>",
            reply_markup=quick_actions_kb(),
        )
        return

    done_count = sum(1 for h in habits if h.get("done"))
    total = len(habits)
    await msg.answer(
        f"🔥 <b>Привычки на сегодня</b> ({done_count}/{total}):\n\n"
        "<i>Нажми на привычку, чтобы отметить ✅</i>",
        reply_markup=habits_inline_kb(habits),
    )


@dp.message(Command("add_habit"))
async def add_habit_cmd(msg: types.Message):
    """Добавить новую привычку: /add_habit [название] [категория]."""
    text = msg.text or msg.caption or ""
    # Убираем команду
    args = re.sub(r"^/add_habit\s+", "", text).strip()
    if not args:
        await msg.answer(
            "📝 <b>Формат:</b> <code>/add_habit [название] [категория]</code>\n"
            "<i>Пример: /add_habit холодный душ утро</i>",
            reply_markup=main_kb(),
        )
        return

    # Разбор: первое слово(а) — название, последнее — категория (если больше одного слова)
    parts = args.rsplit(maxsplit=1)
    if len(parts) == 2:
        name, category = parts
    else:
        name = parts[0]
        category = "общее"

    result = await api_post("/habits", {
        "user_id": USER_ID,
        "name": name,
        "category": category,
    })

    if result and result.get("habit"):
        await msg.answer(
            f"✅ Привычка «<b>{name}</b>» добавлена в категорию «{category}»!\n"
            f"Так держать, Алекс! 💪",
            reply_markup=main_kb(),
        )
    else:
        await msg.answer("😔 Не получилось добавить привычку. Попробуй позже.", reply_markup=main_kb())


@dp.message(Command("supplements"))
@dp.message(F.text == "💊 Добавки")
async def supplements_cmd(msg: types.Message):
    """Показать добавки на сегодня."""
    data = await api_get(f"/supplements/{USER_ID}")
    if not data:
        await msg.answer("😔 Не удалось загрузить добавки. Попробуй позже.", reply_markup=main_kb())
        return

    supps = data.get("supplements", [])
    if not supps:
        await msg.answer(
            "📭 Добавок на сегодня нет.\n"
            "Добавь: <code>/add_supplement [название] [дозировка] [время]</code>",
            reply_markup=quick_actions_kb(),
        )
        return

    taken_count = sum(1 for s in supps if s.get("taken"))
    total = len(supps)
    await msg.answer(
        f"💊 <b>Добавки на сегодня</b> ({taken_count}/{total}):\n\n"
        "<i>Нажми на добавку, чтобы отметить приём 💊</i>",
        reply_markup=supplements_inline_kb(supps),
    )


@dp.message(Command("add_supplement"))
async def add_supplement_cmd(msg: types.Message):
    """Добавить добавку: /add_supplement [название] [дозировка] [время]."""
    text = msg.text or msg.caption or ""
    args = re.sub(r"^/add_supplement\s+", "", text).strip()
    if not args:
        await msg.answer(
            "📝 <b>Формат:</b> <code>/add_supplement [название] [дозировка] [время]</code>\n"
            "<i>Пример: /add_supplement витамин_D 5000_ME утро</i>",
            reply_markup=main_kb(),
        )
        return

    # Разбор: название, дозировка, время
    parts = args.rsplit(maxsplit=2)
    if len(parts) == 3:
        name, dosage, time_of_day = parts
    elif len(parts) == 2:
        name, dosage = parts
        time_of_day = "утро"
    else:
        name = parts[0]
        dosage = ""
        time_of_day = "утро"

    result = await api_post("/supplements", {
        "user_id": USER_ID,
        "name": name,
        "dosage": dosage,
        "time_of_day": time_of_day,
    })

    if result and result.get("supplement"):
        await msg.answer(
            f"✅ Добавка «<b>{name}</b>» ({dosage}, {time_of_day}) добавлена!\n"
            f"Не забудь принять! 💊",
            reply_markup=main_kb(),
        )
    else:
        await msg.answer("😔 Не получилось добавить добавку. Попробуй позже.", reply_markup=main_kb())


@dp.message(Command("workout"))
@dp.message(F.text == "🏋️ Тренировка")
async def workout_cmd(msg: types.Message):
    """Записать тренировку: /workout [тип] [длительность]."""
    text = msg.text or msg.caption or ""
    # Для кнопки "🏋️ Тренировка" — запрашиваем ввод
    if text == "🏋️ Тренировка":
        await msg.answer(
            "🏋️ <b>Запиши тренировку:</b>\n"
            "<code>/workout [тип] [длительность_мин]</code>\n\n"
            "<i>Примеры:</i>\n"
            "<code>/workout силовая 45</code>\n"
            "<code>/workout бег 30</code>\n"
            "<code>/workout йога 20</code>",
            reply_markup=main_kb(),
        )
        return

    args = re.sub(r"^/workout\s+", "", text).strip()
    if not args:
        await msg.answer(
            "📝 <b>Формат:</b> <code>/workout [тип] [длительность_мин]</code>\n"
            "<i>Пример: /workout силовая 45</i>",
            reply_markup=main_kb(),
        )
        return

    parts = args.rsplit(maxsplit=1)
    if len(parts) == 2:
        w_type, duration = parts
        try:
            int(duration)
        except ValueError:
            await msg.answer("⚠️ Длительность должна быть числом (минуты). Пример: <code>/workout бег 30</code>")
            return
    else:
        w_type = parts[0]
        duration = "0"

    habit_name = f"🏋️ тренировка: {w_type} ({duration} мин)"

    result = await api_post("/habits", {
        "user_id": USER_ID,
        "name": habit_name,
        "category": "тренировка",
    })

    if result and result.get("habit"):
        await msg.answer(
            f"✅ Тренировка записана: <b>{w_type}</b> — {duration} мин!\n"
            f"Отличная работа, Алекс! 🔥",
            reply_markup=main_kb(),
        )
    else:
        await msg.answer("😔 Не получилось записать тренировку. Попробуй позже.", reply_markup=main_kb())


@dp.message(Command("sleep"))
@dp.message(F.text == "💤 Сон")
async def sleep_cmd(msg: types.Message):
    """Записать сон: /sleep [часы] [качество]."""
    text = msg.text or msg.caption or ""
    if text == "💤 Сон":
        await msg.answer(
            "💤 <b>Запиши сон:</b>\n"
            "<code>/sleep [часы] [качество]</code>\n\n"
            "<i>Примеры:</i>\n"
            "<code>/sleep 7.5 отлично</code>\n"
            "<code>/sleep 6 нормально</code>\n"
            "<code>/sleep 5 плохо</code>",
            reply_markup=main_kb(),
        )
        return

    args = re.sub(r"^/sleep\s+", "", text).strip()
    if not args:
        await msg.answer(
            "📝 <b>Формат:</b> <code>/sleep [часы] [качество]</code>\n"
            "<i>Пример: /sleep 7.5 отлично</i>",
            reply_markup=main_kb(),
        )
        return

    parts = args.split(maxsplit=1)
    if len(parts) == 2:
        hours, quality = parts
    else:
        hours = parts[0]
        quality = "нормально"

    habit_name = f"💤 сон: {hours}ч ({quality})"

    result = await api_post("/habits", {
        "user_id": USER_ID,
        "name": habit_name,
        "category": "сон",
    })

    if result and result.get("habit"):
        await msg.answer(
            f"✅ Сон записан: <b>{hours}ч</b> — {quality}.\n"
            f"Сладких снов, Алекс! 🌙",
            reply_markup=main_kb(),
        )
    else:
        await msg.answer("😔 Не получилось записать сон. Попробуй позже.", reply_markup=main_kb())


@dp.message(Command("recommend"))
@dp.message(F.text == "🤖 AI-совет")
async def recommend_cmd(msg: types.Message):
    """AI-рекомендации на основе фактов + статистики."""
    loading = await msg.answer("🤖 Анализирую твои данные и научные факты...")

    result = await api_post("/recommendations", {"user_id": USER_ID})

    try:
        await loading.delete()
    except Exception:
        pass

    if result and result.get("recommendations"):
        recs = "\n".join(f"  {i}. {r}" for i, r in enumerate(result["recommendations"], 1))
        text = (
            f"🤖 <b>AI-рекомендации для тебя:</b>\n\n"
            f"{recs}\n\n"
            f"🎯 <b>Фокус дня:</b> {result.get('focus_area', 'здоровый образ жизни')}\n\n"
            f"<i>💬 {result.get('motivation', '')}</i>"
        )
    else:
        text = (
            "🤖 <b>Базовые рекомендации:</b>\n\n"
            "  1. Выпей стакан воды прямо сейчас 💧\n"
            "  2. Проверь список привычек на сегодня 🔥\n"
            "  3. Сделай 5-минутную разминку 🏋️\n\n"
            "<i>Каждый день — шаг к долголетию!</i>"
        )

    await msg.answer(text, reply_markup=main_kb())


@dp.message(Command("stats"))
@dp.message(F.text == "📊 Статистика")
async def stats_cmd(msg: types.Message):
    """Недельная статистика через API /dashboard."""
    loading = await msg.answer("📊 Собираю статистику...")

    data = await api_get(f"/dashboard/{USER_ID}")

    try:
        await loading.delete()
    except Exception:
        pass

    if not data:
        await msg.answer("😔 Не удалось загрузить статистику. Попробуй позже.", reply_markup=main_kb())
        return

    await msg.answer(
        f"📊 <b>Твоя статистика, Алекс:</b>\n\n"
        f"📅 <b>Дата:</b> {data.get('date', '—')}\n"
        f"🔥 <b>Привычек сегодня:</b> {data.get('habits_today', 0)}\n"
        f"✅ <b>Выполнено:</b> {data.get('done_today', 0)} "
        f"({data.get('completion_pct', 0)}%)\n"
        f"💊 <b>Добавок принято:</b> {data.get('supplements_taken', 0)}/{data.get('supplements_total', 0)}\n"
        f"🏆 <b>Стрик:</b> {data.get('streak', 0)} дн.\n"
        f"📋 <b>Всего уникальных привычек:</b> {data.get('total_habits', 0)}\n\n"
        f"<i>Продолжай в том же духе! 💪</i>",
        reply_markup=main_kb(),
    )


# ============================================================
# 🔘  Колбэки (инлайн-кнопки)
# ============================================================

@dp.callback_query(F.data.startswith("habit_toggle:"))
async def habit_toggle_cb(call: types.CallbackQuery):
    """Переключить статус привычки (done/undone)."""
    parts = call.data.split(":")
    if len(parts) != 3:
        await call.answer("⚠️ Неверные данные.")
        return

    habit_id = int(parts[1])
    new_done = int(parts[2])

    result = await api_patch(f"/habits/{habit_id}", {"done": new_done})
    if not result:
        await call.answer("😔 Ошибка обновления.")
        return

    await call.answer("✅ Обновлено!" if new_done else "↩️ Отменено")

    # Обновить сообщение с актуальным списком привычек
    data = await api_get(f"/habits/{USER_ID}")
    if data:
        habits = data.get("habits", [])
        done_count = sum(1 for h in habits if h.get("done"))
        total = len(habits)
        try:
            await call.message.edit_text(
                f"🔥 <b>Привычки на сегодня</b> ({done_count}/{total}):\n\n"
                "<i>Нажми на привычку, чтобы отметить ✅</i>",
                reply_markup=habits_inline_kb(habits),
            )
        except Exception:
            log.exception("Failed to edit habits message")


@dp.callback_query(F.data.startswith("supp_toggle:"))
async def supp_toggle_cb(call: types.CallbackQuery):
    """Переключить статус добавки (taken/untaken)."""
    parts = call.data.split(":")
    if len(parts) != 3:
        await call.answer("⚠️ Неверные данные.")
        return

    supp_id = int(parts[1])
    new_taken = int(parts[2])

    result = await api_patch(f"/supplements/{supp_id}", {"taken": new_taken})
    if not result:
        await call.answer("😔 Ошибка обновления.")
        return

    await call.answer("💊 Принято!" if new_taken else "↩️ Отменено")

    # Обновить сообщение
    data = await api_get(f"/supplements/{USER_ID}")
    if data:
        supps = data.get("supplements", [])
        taken_count = sum(1 for s in supps if s.get("taken"))
        total = len(supps)
        try:
            await call.message.edit_text(
                f"💊 <b>Добавки на сегодня</b> ({taken_count}/{total}):\n\n"
                "<i>Нажми на добавку, чтобы отметить приём 💊</i>",
                reply_markup=supplements_inline_kb(supps),
            )
        except Exception:
            log.exception("Failed to edit supplements message")


@dp.callback_query(F.data.startswith("cmd:"))
async def cmd_cb(call: types.CallbackQuery):
    """Обработка быстрых действий из инлайн-клавиатуры."""
    cmd = call.data.split(":", 1)[1]
    await call.answer()

    if cmd == "habits":
        data = await api_get(f"/habits/{USER_ID}")
        if data:
            habits = data.get("habits", [])
            if habits:
                done_count = sum(1 for h in habits if h.get("done"))
                total = len(habits)
                await call.message.answer(
                    f"🔥 <b>Привычки на сегодня</b> ({done_count}/{total}):\n\n"
                    "<i>Нажми на привычку, чтобы отметить ✅</i>",
                    reply_markup=habits_inline_kb(habits),
                )
            else:
                await call.message.answer(
                    "📭 На сегодня привычек пока нет.\n"
                    "Добавь новую: <code>/add_habit [название] [категория]</code>",
                    reply_markup=main_kb(),
                )
    elif cmd == "supplements":
        data = await api_get(f"/supplements/{USER_ID}")
        if data:
            supps = data.get("supplements", [])
            if supps:
                taken_count = sum(1 for s in supps if s.get("taken"))
                total = len(supps)
                await call.message.answer(
                    f"💊 <b>Добавки на сегодня</b> ({taken_count}/{total}):\n\n"
                    "<i>Нажми на добавку, чтобы отметить приём 💊</i>",
                    reply_markup=supplements_inline_kb(supps),
                )
            else:
                await call.message.answer(
                    "📭 Добавок на сегодня нет.\n"
                    "Добавь: <code>/add_supplement [название] [дозировка] [время]</code>",
                    reply_markup=main_kb(),
                )
    elif cmd == "stats":
        data = await api_get(f"/dashboard/{USER_ID}")
        if data:
            await call.message.answer(
                f"📊 <b>Твоя статистика, Алекс:</b>\n\n"
                f"📅 <b>Дата:</b> {data.get('date', '—')}\n"
                f"🔥 <b>Привычек сегодня:</b> {data.get('habits_today', 0)}\n"
                f"✅ <b>Выполнено:</b> {data.get('done_today', 0)} "
                f"({data.get('completion_pct', 0)}%)\n"
                f"💊 <b>Добавок принято:</b> {data.get('supplements_taken', 0)}/{data.get('supplements_total', 0)}\n"
                f"🏆 <b>Стрик:</b> {data.get('streak', 0)} дн.\n"
                f"📋 <b>Всего уникальных привычек:</b> {data.get('total_habits', 0)}\n\n"
                f"<i>Продолжай в том же духе! 💪</i>",
                reply_markup=main_kb(),
            )
    elif cmd == "recommend":
        loading = await call.message.answer("🤖 Думаю над рекомендациями...")
        try:
            result = await api_post("/recommendations", {"user_id": USER_ID})
        except Exception:
            result = None
        try:
            await loading.delete()
        except Exception:
            pass

        if result and result.get("recommendation"):
            await call.message.answer(
                f"🤖 <b>AI-рекомендация:</b>\n\n{result['recommendation']}",
                reply_markup=main_kb(),
            )
        else:
            await call.message.answer(
                "🤖 <b>Рекомендации пока в разработке</b> 🔧\n\n"
                "Скоро я смогу анализировать твои данные и давать "
                "персонализированные советы по биохакингу!",
                reply_markup=main_kb(),
            )


# === План здоровья ===
@dp.message(Command("plan"))
@dp.message(F.text == "📋 План")
async def plan_cmd(msg: types.Message):
    """Показать последний health-план."""
    loading = await msg.answer("📋 Загружаю план...")
    
    data = await api_get("/plan")
    
    try:
        await loading.delete()
    except Exception:
        pass
    
    if data and data.get("plan"):
        plan = data["plan"]
        text_parts = [f"📋 <b>Твой Health-план (неделя {data.get('week_start', '')})</b>\n"]
        emoji = {"nutrition": "🥗", "sport": "🏋️", "supplements": "💊", "habits": "🧘"}
        
        for section, content in plan.items():
            em = emoji.get(section, "📌")
            text_parts.append(f"\n{em} <b>{section.upper()}</b>")
            
            # Вытащить ключевую информацию
            if isinstance(content, dict):
                if "summary" in content:
                    text_parts.append(f"<i>{content['summary']}</i>")
                for rec in content.get("recommendations", [])[:3]:
                    text_parts.append(f"  • {rec.get('item', rec)}")
                if "principles" in content:
                    text_parts.append(f"\n  Принципы:")
                    for p in content["principles"][:3]:
                        text_parts.append(f"    → {p}")
        
        text_parts.append(f"\n━━━━━━━━━━━\n<i>🔬 На основе проверенных научных фактов</i>")
        await msg.answer("\n".join(text_parts), reply_markup=main_kb())
    else:
        await msg.answer(
            "📭 План пока не сгенерирован.\n\n"
            "Утренний дайджест приходит в 08:00 CEST — там будет свежий план!\n"
            "Или спроси меня о питании/спорте прямо сейчас 💬",
            reply_markup=main_kb(),
        )


# === Корзина покупок ===
@dp.message(Command("shopping"))
@dp.message(F.text == "🛒 Корзина")
async def shopping_cmd(msg: types.Message):
    """Показать корзину покупок на месяц."""
    loading = await msg.answer("🛒 Загружаю корзину...")
    
    data = await api_get("/shopping")
    
    try:
        await loading.delete()
    except Exception:
        pass
    
    if data and data.get("shopping"):
        shop = data["shopping"]
        text_parts = [f"🛒 <b>Корзина здоровья — {shop.get('month', '')}</b>\n"]
        emoji = {"food": "🥗", "supplements": "💊", "sports": "🏋️"}
        
        for cat, items in shop.get("categories", {}).items():
            em = emoji.get(cat, "📦")
            text_parts.append(f"\n{em} <b>{cat.upper()}</b>")
            for item in items[:5]:
                name = item.get("name", "?")
                qty = item.get("quantity", "")
                cost = item.get("approx_cost", "")
                extra = f" — {qty}" if qty else ""
                extra += f" ({cost})" if cost else ""
                text_parts.append(f"  • {name}{extra}")
        
        text_parts.append(f"\n━━━━━━━━━━━\n<i>🔬 На основе твоего health-плана</i>")
        await msg.answer("\n".join(text_parts), reply_markup=main_kb())
    else:
        await msg.answer(
            "📭 Корзина пока не сгенерирована.\n\n"
            "Она создаётся автоматически вместе с планом.\n"
            "Спроси меня — я помогу подобрать продукты и бады! 💬",
            reply_markup=main_kb(),
        )


# ============================================================
# 🆘  Fallback: неизвестный текст
# ============================================================

EXCLUDE = {"🔥 Привычки", "💊 Добавки", "🏋️ Тренировка", "💤 Сон", "🤖 AI-совет", "📊 Статистика", "📋 План", "🛒 Корзина"}

@dp.message(F.text & ~F.text.in_(EXCLUDE) & ~F.text.startswith("/"))
async def chat_with_ai(msg: types.Message):
    """NL-чат: любой текст → AI-ответ на основе фактов и плана."""
    text = msg.text or msg.caption or ""
    if not text.strip():
        return
    
    loading = await msg.answer("💬 Думаю...")
    
    result = await api_post("/chat", {"user_id": USER_ID, "message": text})
    
    try:
        await loading.delete()
    except Exception:
        pass
    
    if result and result.get("response"):
        await msg.answer(result["response"], reply_markup=main_kb())
    else:
        await msg.answer(
            "😔 Не получилось ответить. Попробуй позже или нажми кнопку!",
            reply_markup=main_kb(),
        )


# ============================================================
# 🚀  Точка входа
# ============================================================

async def main():
    log.info("💪 Health Bot стартует...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("🛑 Health Bot остановлен.")
