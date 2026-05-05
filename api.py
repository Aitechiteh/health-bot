#!/usr/bin/env python3
"""💪 Health Tracking API — FastAPI backend. Трекинг привычек, добавок и YouTube-источников."""

import sqlite3, json
from datetime import datetime, date
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# === Настройки ===
DB_PATH = Path(__file__).parent / "health.db"

app = FastAPI(title="💪 Health Tracking API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])


# === Модели ===
class HabitCreate(BaseModel):
    user_id: str
    name: str
    category: str


class HabitToggle(BaseModel):
    done: int


class SupplementCreate(BaseModel):
    user_id: str
    name: str
    dosage: str
    time_of_day: str


class SupplementToggle(BaseModel):
    taken: int


# === DB ===
def get_db():
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    return db


def init_db():
    db = get_db()
    db.executescript("""
        CREATE TABLE IF NOT EXISTS habits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            name TEXT NOT NULL,
            category TEXT DEFAULT 'общее',
            done INTEGER DEFAULT 0,
            date TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS supplements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            name TEXT NOT NULL,
            dosage TEXT DEFAULT '',
            time_of_day TEXT DEFAULT 'утро',
            taken INTEGER DEFAULT 0,
            date TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS youtube_sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_name TEXT NOT NULL,
            video_url TEXT NOT NULL,
            transcript TEXT,
            facts_json TEXT,
            credibility_score REAL DEFAULT 0.0,
            analyzed INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        );
    """)
    db.commit()
    db.close()


init_db()


# === Сегодняшняя дата ===
def today_str() -> str:
    return date.today().isoformat()


# === Эндпоинты: Привычки ===
@app.get("/habits/{user_id}")
def get_habits(user_id: str):
    """Список привычек пользователя за сегодня."""
    db = get_db()
    today = today_str()
    rows = db.execute(
        "SELECT * FROM habits WHERE user_id=? AND date=? ORDER BY category, created_at DESC",
        (user_id, today)
    ).fetchall()
    db.close()
    return {"habits": [dict(r) for r in rows], "total": len(rows)}


@app.post("/habits")
def create_habit(habit: HabitCreate):
    """Создать новую привычку на сегодня."""
    db = get_db()
    today = today_str()
    cur = db.execute(
        "INSERT INTO habits (user_id, name, category, date) VALUES (?, ?, ?, ?)",
        (habit.user_id, habit.name, habit.category, today)
    )
    db.commit()
    habit_id = cur.lastrowid
    row = db.execute("SELECT * FROM habits WHERE id=?", (habit_id,)).fetchone()
    db.close()
    return {"habit": dict(row), "message": "Привычка добавлена"}


@app.patch("/habits/{habit_id}")
def toggle_habit(habit_id: int, data: HabitToggle):
    """Отметить привычку выполненной/невыполненной."""
    db = get_db()
    db.execute("UPDATE habits SET done=? WHERE id=?", (data.done, habit_id))
    db.commit()
    row = db.execute("SELECT * FROM habits WHERE id=?", (habit_id,)).fetchone()
    db.close()
    return {"habit": dict(row) if row else None, "message": "Обновлено"}


@app.delete("/habits/{habit_id}")
def delete_habit(habit_id: int):
    """Удалить привычку."""
    db = get_db()
    db.execute("DELETE FROM habits WHERE id=?", (habit_id,))
    db.commit()
    db.close()
    return {"ok": True, "message": "Привычка удалена"}


# === Эндпоинты: Добавки ===
@app.get("/supplements/{user_id}")
def get_supplements(user_id: str):
    """Список добавок пользователя за сегодня."""
    db = get_db()
    today = today_str()
    rows = db.execute(
        "SELECT * FROM supplements WHERE user_id=? AND date=? ORDER BY time_of_day, name",
        (user_id, today)
    ).fetchall()
    db.close()
    return {"supplements": [dict(r) for r in rows], "total": len(rows)}


@app.post("/supplements")
def create_supplement(supp: SupplementCreate):
    """Добавить добавку на сегодня."""
    db = get_db()
    today = today_str()
    cur = db.execute(
        "INSERT INTO supplements (user_id, name, dosage, time_of_day, date) VALUES (?, ?, ?, ?, ?)",
        (supp.user_id, supp.name, supp.dosage, supp.time_of_day, today)
    )
    db.commit()
    supp_id = cur.lastrowid
    row = db.execute("SELECT * FROM supplements WHERE id=?", (supp_id,)).fetchone()
    db.close()
    return {"supplement": dict(row), "message": "Добавка добавлена"}


@app.patch("/supplements/{supp_id}")
def toggle_supplement(supp_id: int, data: SupplementToggle):
    """Отметить добавку принятой/непринятой."""
    db = get_db()
    db.execute("UPDATE supplements SET taken=? WHERE id=?", (data.taken, supp_id))
    db.commit()
    row = db.execute("SELECT * FROM supplements WHERE id=?", (supp_id,)).fetchone()
    db.close()
    return {"supplement": dict(row) if row else None, "message": "Обновлено"}


@app.delete("/supplements/{supp_id}")
def delete_supplement(supp_id: int):
    """Удалить добавку."""
    db = get_db()
    db.execute("DELETE FROM supplements WHERE id=?", (supp_id,))
    db.commit()
    db.close()
    return {"ok": True, "message": "Добавка удалена"}


# === Дашборд ===
@app.get("/dashboard/{user_id}")
def get_dashboard(user_id: str):
    """Агрегированная статистика пользователя."""
    db = get_db()
    today = today_str()

    # Всего привычек (шаблонов) — уникальные названия
    total_habits = db.execute(
        "SELECT COUNT(DISTINCT name) FROM habits WHERE user_id=?", (user_id,)
    ).fetchone()[0]

    # Привычки выполненные сегодня
    done_today = db.execute(
        "SELECT COUNT(*) FROM habits WHERE user_id=? AND date=? AND done=1",
        (user_id, today)
    ).fetchone()[0]

    # Всего привычек на сегодня
    habits_today = db.execute(
        "SELECT COUNT(*) FROM habits WHERE user_id=? AND date=?",
        (user_id, today)
    ).fetchone()[0]

    # Добавки принятые сегодня
    supps_taken = db.execute(
        "SELECT COUNT(*) FROM supplements WHERE user_id=? AND date=? AND taken=1",
        (user_id, today)
    ).fetchone()[0]

    # Всего добавок на сегодня
    supps_total = db.execute(
        "SELECT COUNT(*) FROM supplements WHERE user_id=? AND date=?",
        (user_id, today)
    ).fetchone()[0]

    # Расчёт стрика (последовательных дней с выполненными привычками)
    streak = 0
    all_dates = db.execute(
        "SELECT DISTINCT date FROM habits WHERE user_id=? AND done=1 ORDER BY date DESC",
        (user_id,)
    ).fetchall()

    if all_dates:
        dates = [row["date"] for row in all_dates]
        current = date.today()
        for d_str in dates:
            d = date.fromisoformat(d_str)
            if d == current:
                streak += 1
                current = date.fromordinal(current.toordinal() - 1)
            elif d == date.fromordinal(current.toordinal() + 1):
                # пропуск одного дня — продолжаем
                pass
            else:
                break

    db.close()

    return {
        "user_id": user_id,
        "date": today,
        "total_habits": total_habits,
        "habits_today": habits_today,
        "done_today": done_today,
        "supplements_taken": supps_taken,
        "supplements_total": supps_total,
        "streak": streak,
        "completion_pct": round(done_today / habits_today * 100) if habits_today > 0 else 0,
    }


# === Health Check ===
@app.get("/health")
def health():
    """Проверка работоспособности сервиса."""
    try:
        db = get_db()
        db.execute("SELECT 1 FROM habits LIMIT 1")
        db.close()
        db_ok = True
    except:
        db_ok = False

    return {
        "status": "ok" if db_ok else "degraded",
        "service": "💪 Health Tracking API",
        "database": "connected" if db_ok else "disconnected",
        "timestamp": datetime.now().isoformat(),
    }


# === YouTube Digest ===
@app.get("/digest")
def get_digest():
    """Последний AI-дайджест (факты из youtube_sources за сегодня)."""
    db = get_db()
    today = today_str()
    rows = db.execute(
        "SELECT * FROM youtube_sources WHERE analyzed=1 AND created_at LIKE ? ORDER BY credibility_score DESC LIMIT 20",
        (f"{today}%",)
    ).fetchall()
    
    if not rows:
        rows = db.execute(
            "SELECT * FROM youtube_sources WHERE analyzed=1 ORDER BY created_at DESC LIMIT 20"
        ).fetchall()
    
    result = []
    for r in rows:
        result.append({
            "channel": r["channel_name"],
            "video_url": r["video_url"],
            "facts": json.loads(r["facts_json"]),
            "credibility": r["credibility_score"],
            "created": r["created_at"],
        })
    
    db.close()
    return {"digest": result, "total_videos": len(result), "total_facts": sum(len(r["facts"]) for r in result)}




# === Health Plan ===
@app.get("/plan")
def get_plan():
    """Последний персональный health-план."""
    db = get_db()
    try:
        # Проверить что таблица существует
        db.execute("SELECT 1 FROM health_plans LIMIT 1")
    except:
        db.close()
        return {"plan": None, "message": "План ещё не сгенерирован"}
    
    row = db.execute(
        "SELECT week_start, section, content FROM health_plans WHERE week_start = (SELECT MAX(week_start) FROM health_plans) ORDER BY section"
    ).fetchall()
    db.close()
    
    if not row:
        return {"plan": None, "message": "План ещё не сгенерирован"}
    
    plan = {}
    for week_start, section, content in row:
        plan[section] = json.loads(content)
    return {"plan": plan, "week_start": row[0]["week_start"]}


# === Shopping List ===
@app.get("/shopping")
def get_shopping():
    """Последняя корзина покупок."""
    db = get_db()
    row = db.execute(
        "SELECT month FROM shopping_lists ORDER BY month DESC LIMIT 1"
    ).fetchone()
    if not row:
        return {"shopping": None, "message": "Корзина ещё не сгенерирована"}
    
    month = row["month"]
    items = db.execute(
        "SELECT category, items_json FROM shopping_lists WHERE month=?", (month,)
    ).fetchall()
    db.close()
    
    shopping = {"month": month, "categories": {}}
    for cat, items_json in items:
        shopping["categories"][cat] = json.loads(items_json)
    return {"shopping": shopping}


# === Verified Facts ===
@app.get("/verified")
def get_verified():
    """Проверенные факты (последние 20)."""
    db = get_db()
    rows = db.execute(
        "SELECT vf.*, ys.channel_name FROM verified_facts vf JOIN youtube_sources ys ON vf.source_id = ys.id ORDER BY vf.support_score DESC LIMIT 20"
    ).fetchall()
    db.close()
    return {"verified_facts": [dict(r) for r in rows], "total": len(rows)}


# === Reminders ===
@app.get("/reminders/{user_id}")
def get_reminders(user_id: str):
    """Активные напоминалки пользователя."""
    db = get_db()
    rows = db.execute(
        "SELECT * FROM reminders WHERE user_id=? AND active=1 ORDER BY time_of_day", (user_id,)
    ).fetchall()
    db.close()
    return {"reminders": [dict(r) for r in rows], "total": len(rows)}


# === AI Chat (NL-общение) ===
class ChatRequest(BaseModel):
    user_id: str
    message: str


@app.post("/chat")
def chat_with_ai(req: ChatRequest):
    """NL-чат с AI на основе проверенных фактов и профиля."""
    from urllib.request import Request, urlopen
    
    # Загрузить контекст: verified facts + план
    db = get_db()
    facts = db.execute("""
        SELECT vf.fact, vf.recommendation, vf.support_score 
        FROM verified_facts vf 
        WHERE vf.consensus='supported' 
        ORDER BY vf.support_score DESC LIMIT 15
    """).fetchall()
    
    plan = db.execute("""
        SELECT section, content FROM health_plans 
        WHERE week_start=(SELECT MAX(week_start) FROM health_plans)
    """).fetchall()
    db.close()
    
    facts_text = "\n".join(f"{i}. {r['fact']} (score: {r['support_score']:.2f})" for i, r in enumerate(facts, 1))
    plan_text = "\n".join(f"{r['section']}: {r['content'][:300]}" for r in plan)
    
    prompt = f"""Ты — AI health-ассистент для Алекса (46 лет, 74-76 кг, 174 см, живёт в Германии, цель — долголетие).
Отвечай на русском, кратко и по делу, опираясь на проверенные научные факты.

ПРОВЕРЕННЫЕ ФАКТЫ:
{facts_text}

ПЛАН ЗДОРОВЬЯ:
{plan_text}

ВОПРОС ПОЛЬЗОВАТЕЛЯ: {req.message}

Ответь полезно и персонализированно. Если вопрос не про здоровье — мягко переведи в тему. Держи ответ ≤400 слов."""
    
    try:
        data = json.dumps({
            "model": "gemma4:31b",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.5, "max_tokens": 800,
        }).encode()
        
        llm_req = Request("http://127.0.0.1:4000/chat/completions", data=data, method="POST")
        llm_req.add_header("Content-Type", "application/json")
        llm_req.add_header("Authorization", "Bearer sk-4e9e073d30502f092ffd3ddfa29e9c46")
        
        with urlopen(llm_req, timeout=60) as resp:
            body = json.loads(resp.read())
            return {"response": body["choices"][0]["message"]["content"]}
    except Exception as e:
        return {"response": f"Извини, не могу ответить сейчас. Ошибка: {str(e)[:100]}"}


# === AI Recommendations ===
class RecommendRequest(BaseModel):
    user_id: str


@app.post("/recommendations")
def get_recommendations(req: RecommendRequest):
    """Персональные AI-рекомендации на основе фактов и плана."""
    from urllib.request import Request, urlopen
    
    db = get_db()
    
    # Статистика пользователя
    today = today_str()
    stats = db.execute("""
        SELECT 
            (SELECT COUNT(*) FROM habits WHERE user_id=? AND date=? AND done=1) as done,
            (SELECT COUNT(*) FROM habits WHERE user_id=? AND date=?) as total,
            (SELECT COUNT(*) FROM supplements WHERE user_id=? AND date=? AND taken=1) as supp_taken,
            (SELECT COUNT(*) FROM supplements WHERE user_id=? AND date=?) as supp_total
    """, (req.user_id, today, req.user_id, today, req.user_id, today, req.user_id, today)).fetchone()
    
    # Топ-факты + план
    facts = db.execute("""
        SELECT vf.fact, vf.recommendation, vf.support_score, ys.channel_name
        FROM verified_facts vf JOIN youtube_sources ys ON vf.source_id=ys.id
        WHERE vf.consensus='supported' ORDER BY vf.support_score DESC LIMIT 10
    """).fetchall()
    
    plan = db.execute("""
        SELECT section, content FROM health_plans 
        WHERE week_start=(SELECT MAX(week_start) FROM health_plans)
    """).fetchall()
    db.close()
    
    plan_text = "\n".join(f"{r['section']}: {r['content'][:250]}" for r in plan)
    facts_text = "\n".join(f"{r['fact']} — {r['recommendation']}" for r in facts)
    
    prompt = f"""Дай 3-5 персонализированных рекомендаций Алексу по здоровью. Профиль: 46 лет, 74-76 кг, Германия.

СТАТИСТИКА СЕГОДНЯ: {stats['done'] if stats else 0}/{stats['total'] if stats else 0} привычек, {stats['supp_taken'] if stats else 0}/{stats['supp_total'] if stats else 0} добавок.

ПЛАН: {plan_text}
ФАКТЫ: {facts_text}

Ответь СТРОГО в JSON:
{{"recommendations": ["рекомендация 1", "рекомендация 2", ...], "motivation": "мотивирующая фраза", "focus_area": "на чём фокус сегодня"}}"""
    
    try:
        data = json.dumps({
            "model": "gemma4:31b",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.6, "max_tokens": 1000,
        }).encode()
        
        llm_req = Request("http://127.0.0.1:4000/chat/completions", data=data, method="POST")
        llm_req.add_header("Content-Type", "application/json")
        llm_req.add_header("Authorization", "Bearer sk-4e9e073d30502f092ffd3ddfa29e9c46")
        
        with urlopen(llm_req, timeout=90) as resp:
            body = json.loads(resp.read())
            raw = body["choices"][0]["message"]["content"].strip()
            if raw.startswith("```"): raw = "\n".join(l for l in raw.split("\n") if not l.startswith("```"))
            result = json.loads(raw)
            
            return {
                "recommendations": result.get("recommendations", []),
                "motivation": result.get("motivation", ""),
                "focus_area": result.get("focus_area", ""),
            }
    except Exception:
        return {
            "recommendations": [
                "Выпей стакан воды прямо сейчас 💧",
                "Проверь список привычек на сегодня 🔥",
                "Сделай 5-минутную разминку для спины 🏋️"
            ],
            "motivation": "Алекс, ты на верном пути! Каждый день — шаг к долголетию.",
            "focus_area": "водный баланс и движение",
        }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8082)
