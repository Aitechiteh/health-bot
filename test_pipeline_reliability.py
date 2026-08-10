import importlib.util
import json
import sqlite3
from pathlib import Path


def load(name: str):
    path = Path(__file__).with_name(f"{name}.py")
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_fact_checker_retries_only_missing_facts(tmp_path):
    fc = load("fact_checker")
    setattr(fc, "DB", tmp_path / "health.db")
    db = sqlite3.connect(fc.DB)
    db.executescript("""
        CREATE TABLE youtube_sources (
          id INTEGER PRIMARY KEY, channel_name TEXT, video_url TEXT,
          facts_json TEXT, credibility_score REAL, analyzed INTEGER
        );
        CREATE TABLE verified_facts (
          id INTEGER PRIMARY KEY, source_id INTEGER, fact TEXT,
          recommendation TEXT, original_credibility REAL,
          support_score INTEGER, consensus TEXT, critique TEXT,
          verified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    facts = [{"fact": "done", "recommendation": "a"},
             {"fact": "pending", "recommendation": "b"}]
    db.execute("INSERT INTO youtube_sources VALUES (1,'c','u',?,8,1)",
               (json.dumps(facts),))
    db.execute("INSERT INTO verified_facts(source_id,fact) VALUES (1,'done')")
    db.commit()
    db.close()

    rows = fc.get_unverified()
    assert [f["fact"] for f in rows[0]["facts"]] == ["pending"]
    fc.save_verified(1, "pending", "b", 8, 7, "ok", "")
    fc.save_verified(1, "pending", "b", 8, 7, "ok", "")
    db = sqlite3.connect(fc.DB)
    assert db.execute(
        "SELECT count(*) FROM verified_facts WHERE source_id=1 AND fact='pending'"
    ).fetchone()[0] == 1


def test_digest_never_marks_empty_analysis_complete(tmp_path):
    digest = load("digest")
    setattr(digest, "DB", tmp_path / "health.db")
    db = sqlite3.connect(digest.DB)
    db.execute("""CREATE TABLE youtube_sources (
      id INTEGER PRIMARY KEY, channel_name TEXT, video_url TEXT UNIQUE,
      transcript TEXT, facts_json TEXT, credibility_score REAL, analyzed INTEGER
    )""")
    db.commit()
    db.close()
    video = {"channel": "c", "url": "u", "description": "d"}

    assert digest.save_to_db(video, []) is False
    db = sqlite3.connect(digest.DB)
    assert db.execute("SELECT count(*) FROM youtube_sources").fetchone()[0] == 0
    db.close()

    assert digest.save_to_db(video, [{"credibility": 8, "fact": "x"}]) is True
    assert digest.save_to_db(video, [{"credibility": 9, "fact": "y"}]) is True
    db = sqlite3.connect(digest.DB)
    row = db.execute("SELECT count(*), facts_json FROM youtube_sources").fetchone()
    assert row[0] == 1 and '"y"' in row[1]


def test_digest_parse_failure_does_not_require_video_id(monkeypatch):
    digest = load("digest")
    monkeypatch.setattr(digest, "call_llm", lambda _: "not-json")
    video = {"channel": "c", "url": "u", "title": "t", "description": "d"}
    assert digest.analyze_video(video) == []


def test_historical_import_is_side_effect_free():
    historical = load("historical")
    assert callable(historical.main)


def test_historical_llm_call_builds_authorized_request(monkeypatch):
    historical = load("historical")

    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *_):
            return False
        def read(self):
            return b'{"choices":[{"message":{"content":"[]"}}]}'

    seen = []
    monkeypatch.setattr(historical.urllib.request, "urlopen", lambda req, **_: seen.append(req) or Response())
    assert historical.call_llm("x") == "[]"
    assert seen[0].get_header("Authorization").startswith("Bearer ")


def test_digest_delivery_failure_is_reported(monkeypatch):
    digest = load("digest")
    monkeypatch.setattr(digest, "BOT_TOKEN", "test")
    monkeypatch.setattr(digest, "CHAT_ID", "1")
    monkeypatch.setattr("urllib.request.urlopen", lambda *_a, **_k: (_ for _ in ()).throw(OSError("offline")))
    assert digest.send_telegram("x") is False


def test_digest_main_fails_when_delivery_fails(monkeypatch):
    digest = load("digest")
    monkeypatch.setattr(digest, "collect_videos", lambda: [])
    monkeypatch.setattr(digest, "send_telegram", lambda _: False)
    assert digest.main() == 1


def test_pipeline_steps_fail_when_prerequisites_are_missing(monkeypatch):
    planner = load("health_planner")
    monkeypatch.setattr(planner, "init_db", lambda: None)
    monkeypatch.setattr(planner, "get_recent_plans", lambda **_: ({}, set()))
    monkeypatch.setattr(planner, "get_supported_facts", lambda **_: [])
    assert planner.main() == 1

    shopping = load("shopping_list")
    monkeypatch.setattr(shopping, "get_latest_plan", lambda: {})
    assert shopping.main() == 1


def test_digest_parses_json_before_trailing_model_text(monkeypatch):
    digest = load("digest")
    raw = '[{"fact":"x","recommendation":"y","credibility":0.8}] trailing'
    monkeypatch.setattr(digest, "call_llm", lambda _: raw)
    video = {"title": "t", "description": "d", "channel": "c"}
    assert digest.analyze_video(video)[0]["fact"] == "x"


def test_digest_rejects_invalid_credibility(monkeypatch):
    digest = load("digest")
    raw = '[{"fact":"a","credibility":"high"},{"fact":"b","credibility":2}]'
    monkeypatch.setattr(digest, "call_llm", lambda _: raw)
    video = {"title": "t", "description": "d", "channel": "c"}
    assert digest.analyze_video(video) == []


def test_pipeline_fails_closed(monkeypatch, tmp_path):
    pipeline = load("pipeline")
    outcomes = iter([True, False])
    monkeypatch.setattr(pipeline, "run_step", lambda *_: next(outcomes))
    pipeline.SCRIPTS["plan_html"] = tmp_path / "missing.html"
    assert pipeline.main() == 1


def test_personalize_preserves_profile_on_partial_failure(monkeypatch):
    personalize = load("personalize")
    monkeypatch.setattr(personalize, "init_schema", lambda: None)
    monkeypatch.setattr(personalize, "gather_context", lambda: {
        "verified_facts": [], "longevity_news": [], "health_plan": {}
    })
    monkeypatch.setattr(personalize, "analyze_supplements", lambda _: [{"item": "x"}])
    monkeypatch.setattr(personalize, "analyze_nutrition", lambda _: [{"foo": "bar"}])
    monkeypatch.setattr(personalize, "analyze_sport", lambda _: [{"item": "x"}])
    monkeypatch.setattr(personalize, "analyze_sleep", lambda _: [{"item": "x"}])
    saved = []
    monkeypatch.setattr(personalize, "save_profiles", lambda *args: saved.append(args))
    assert personalize.main() == 1
    assert saved == []


def test_personalize_profile_and_schedule_rollback_together(monkeypatch, tmp_path):
    personalize = load("personalize")
    db_path = tmp_path / "health.db"

    def get_db():
        return sqlite3.connect(db_path)

    monkeypatch.setattr(personalize, "get_db", get_db)
    db = get_db()
    db.executescript("""
        CREATE TABLE personal_profile (
          id INTEGER PRIMARY KEY, section TEXT, priority INTEGER, item TEXT,
          dosage TEXT, timing TEXT, reason TEXT, source_id TEXT, category TEXT
        );
        CREATE TABLE weekly_schedule (
          id INTEGER PRIMARY KEY, day_of_week INTEGER, time_of_day TEXT,
          activity TEXT, category TEXT, duration_min INTEGER
        );
        INSERT INTO personal_profile(section, item) VALUES ('nutrition', 'old');
        INSERT INTO weekly_schedule(day_of_week, activity) VALUES (1, 'old');
    """)
    db.commit()
    db.close()

    monkeypatch.setattr(personalize, "generate_weekly_schedule", lambda _db: (_ for _ in ()).throw(RuntimeError("boom")))
    try:
        personalize.save_profiles({"nutrition": [{"item": "new"}]})
    except RuntimeError:
        pass
    else:
        raise AssertionError("save_profiles must propagate transaction failure")

    db = get_db()
    assert db.execute("SELECT item FROM personal_profile").fetchall() == [("old",)]
    assert db.execute("SELECT activity FROM weekly_schedule").fetchall() == [("old",)]
    db.close()


def test_personalize_parses_first_complete_json_value():
    personalize = load("personalize")
    raw = 'preface\n[{"item":"x"}]\ntrailing [not json]'
    assert personalize.parse_llm_json(raw) == [{"item": "x"}]


def test_personalize_accepts_single_item_response():
    personalize = load("personalize")
    item = {"item": "x", "priority": 1}
    assert personalize.normalize_items(item, "nutrition") == [item]


def test_fact_checker_parser_rejects_non_dicts_and_ignores_trailing_text():
    checker = load("fact_checker")
    raw = 'preface [{"fact_id":"1/1"}, "bad"] trailing [not json]'
    assert checker.parse_json(raw) == [{"fact_id": "1/1"}]


def test_api_fresh_schema_supports_digest_upsert(tmp_path):
    api = load("api")
    setattr(api, "DB_PATH", tmp_path / "health.db")
    api.init_db()
    db = sqlite3.connect(api.DB_PATH)
    indexes = db.execute("PRAGMA index_list(youtube_sources)").fetchall()
    assert any(row[2] for row in indexes)
    db.close()
