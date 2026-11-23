"""The question template bank (scripts/data/question_templates.json), its loader, and how
interviews pick from it. Rules-only provider: no network, no key."""

import difflib
import re
from collections import Counter
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.config import settings
from app.models import InterviewSession, QuestionTemplate, SessionAnswer, User
from app.services import ai, interview
from app.services.ai.base import LLMProvider
from scripts import load_question_templates as loader
from scripts import seed_config as cfg
from tests.conftest import candidate_payload, signup_full

TEMPLATES = loader.read_templates()
SKILL_NAMES = [s[0] for s in cfg.SKILLS]
BEHAVIOURAL = {"Communication", "Teamwork", "Problem solving", "Time management", "Leadership"}
CODING = re.compile(r"\b(write (a |the |some )?(code|function|program|script|query)|implement|algorithm|code snippet|"
                    r"output of|what does this code|run this|leetcode|big-o)\b", re.I)
LONG_ANSWER = (
    "When I worked on a project in my last semester I had to plan the work carefully. First I listed the steps, "
    "for example the data, the checks and the result, and then I tested each one. As a result the work was "
    "correct and I learned to explain my choices and to ask for help early."
)


def by_skill() -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for t in TEMPLATES:
        out.setdefault(t["skill"], []).append(t)
    return out


def norm(text: str) -> str:
    return re.sub(r"[^a-z ]", "", text.lower())


@pytest.fixture(autouse=True)
def rules_only(monkeypatch):
    monkeypatch.setattr(settings, "ai_provider", "rules")


# ---------- the data file ----------

def test_every_skill_has_enough_templates():
    groups = by_skill()
    assert set(groups) == set(SKILL_NAMES)
    for skill, items in groups.items():
        assert len(items) >= (6 if skill in BEHAVIOURAL else 5), skill


def test_technical_skills_have_the_planned_mix():
    for skill, items in by_skill().items():
        if skill in BEHAVIOURAL:
            assert all(t["type"] == "behavioral" and t["kind"] == "star" for t in items), skill
            continue
        kinds = Counter(t["kind"] for t in items)
        assert kinds["concept"] >= 2 and kinds["applied"] >= 2 and 1 <= kinds["experience"] <= 2, skill
        assert all(t["type"] == "technical" for t in items), skill
        levels = Counter(t["difficulty"] for t in items)
        assert levels["easy"] >= 2 and levels["medium"] >= 2, skill


def test_every_template_is_complete():
    for t in TEMPLATES:
        assert t["difficulty"] in ("easy", "medium"), t["id"]
        assert t["type"] in ("technical", "behavioral"), t["id"]
        assert 4 <= len(t["keywords"]) <= 6 and len(set(t["keywords"])) == len(t["keywords"]), t["id"]
        assert all(k == k.strip() and k for k in t["keywords"]), t["id"]
        assert t["followUp"].strip().endswith("?") and t["followUp"].count("?") == 1 and t["followUp"] != t["text"], t["id"]
        assert 20 <= len(t["text"]) <= 300 and len(t["id"]) <= 40, t["id"]
        assert not CODING.search(t["text"]), t["id"]


def test_no_duplicate_or_near_duplicate_questions():
    assert len({t["id"] for t in TEMPLATES}) == len(TEMPLATES)
    assert len({norm(t["text"]) for t in TEMPLATES}) == len(TEMPLATES)
    # the older seed questions stay in the database, so the new ones must differ from them too
    pool = [(t["skill"], t["text"], t["id"]) for t in TEMPLATES] + [(q[1], q[3], q[0]) for q in cfg.QUESTIONS]
    groups: dict[str, list[tuple[str, str]]] = {}
    for skill, text, id_ in pool:
        groups.setdefault(skill, []).append((id_, norm(text)))
    for skill, items in groups.items():
        for i, (a, ta) in enumerate(items):
            for b, tb in items[i + 1:]:
                assert difflib.SequenceMatcher(None, ta, tb).ratio() < 0.75, (skill, a, b)


# ---------- the loader ----------

def _count(db):
    return db.scalar(select(func.count()).select_from(QuestionTemplate))


def _with_text(db, text):
    return db.scalar(select(func.count()).select_from(QuestionTemplate).where(QuestionTemplate.text == text))


def test_loader_adds_everything_once(db):
    cfg.apply(db)
    db.commit()
    before = _count(db)
    first = loader.load(db)
    db.commit()
    assert first["added"] == len(TEMPLATES) and first["existing"] == 0 and not first["skipped"]
    assert _count(db) == before + len(TEMPLATES)
    second = loader.load(db)
    db.commit()
    assert second["added"] == 0 and second["existing"] == len(TEMPLATES)
    assert _count(db) == before + len(TEMPLATES)
    assert db.get(QuestionTemplate, TEMPLATES[0]["id"]).difficulty in ("easy", "medium")


def test_loader_keeps_existing_and_edited_templates(db):
    cfg.apply(db)
    first = TEMPLATES[0]
    loader.load(db, [first])
    db.get(QuestionTemplate, first["id"]).keywords = ["edited by admin"]
    db.commit()
    loader.load(db, [{**first, "id": "x", "text": first["text"].upper()}])  # same text, other case
    db.commit()
    assert db.get(QuestionTemplate, first["id"]).keywords == ["edited by admin"]
    assert db.get(QuestionTemplate, "x") is None
    assert _with_text(db, first["text"]) == 1


def test_loader_never_deletes_older_templates(db):
    cfg.apply(db)
    db.commit()
    before = {q.id for q in db.scalars(select(QuestionTemplate))}
    loader.load(db)
    db.commit()
    assert before <= {q.id for q in db.scalars(select(QuestionTemplate))}


def test_loader_skips_unknown_skills(db):
    report = loader.load(db, [TEMPLATES[0]])
    assert report["added"] == 0 and report["skipped"] == [TEMPLATES[0]["skill"]]


def test_loader_uses_a_new_id_when_the_id_is_taken(db):
    cfg.apply(db)
    taken = TEMPLATES[0]
    db.add(QuestionTemplate(id=taken["id"], skill_id=cfg.slug(taken["skill"]), type="technical",
                            text="An admin question with the same id", keywords=[], difficulty="easy"))
    db.commit()
    loader.load(db, [taken])
    db.commit()
    assert _with_text(db, taken["text"]) == 1


# ---------- selection ----------

@pytest.fixture
def auth(client, db):
    cfg.apply(db)
    loader.load(db)
    db.commit()
    body = signup_full(client, candidate_payload())
    return {"Authorization": f"Bearer {body['token']}"}


def sync_session(client, auth, session_id, skill_scores):
    answers = [{"questionId": None, "question": f"{s}?", "skill": s, "type": "technical", "score": sc, "criteria": {}}
               for s, sc in skill_scores.items()]
    res = client.post("/api/sessions", headers=auth, json={
        "id": session_id, "roleId": "backend", "mode": "text", "score": 50, "answers": answers})
    assert res.status_code == 201, res.text


def start(client, auth, count=4):
    res = client.post("/api/interviews", headers=auth, json={"roleId": "backend", "mode": "text", "count": count})
    assert res.status_code == 201, res.text
    return res.json()


def run_session(client, auth, count=4):
    session = start(client, auth, count)
    for q in session["questions"]:
        res = client.post(f"/api/interviews/{session['id']}/answers", headers=auth,
                          json={"questionId": q["id"], "answer": LONG_ANSWER})
        assert res.status_code == 200, res.text
    return session


def test_two_sessions_in_a_row_on_the_same_weak_skill_get_different_questions(client, auth):
    sync_session(client, auth, "w1", {"SQL": 35, "Python": 80})
    sync_session(client, auth, "w2", {"SQL": 40, "Python": 85})
    asked = []
    for _ in range(3):
        session = run_session(client, auth)
        first = session["questions"][0]
        assert first["skill"] == "SQL" and first["reason"] == "weakness"
        asked.append(first["templateId"])
    assert len(set(asked)) == 3 and None not in asked


def test_a_question_answered_in_the_last_sessions_is_not_repeated(client, auth):
    first = run_session(client, auth, count=6)
    second = run_session(client, auth, count=6)
    assert {q["templateId"] for q in first["questions"]}.isdisjoint({q["templateId"] for q in second["questions"]})


def _answered_session(db, user_id, template_ids, age_days):
    when = datetime.now(timezone.utc) - timedelta(days=age_days)
    s = InterviewSession(id=f"old-{age_days}", candidate_id=user_id, role_id="backend", mode="text",
                         status="completed", score=50, date=when)
    db.add(s)
    db.flush()
    for i, tid in enumerate(template_ids):
        t = db.get(QuestionTemplate, tid)
        db.add(SessionAnswer(id=f"a-{age_days}-{i}", session_id=s.id, skill_id=t.skill_id, question_id=tid, position=i,
                             question=t.text, type=t.type, answer="x", answered_at=when))
    db.commit()


def _sql_ids(db):
    return sorted(t.id for t in db.scalars(select(QuestionTemplate).where(QuestionTemplate.skill_id == "sql")))


def _user(db):
    return db.scalars(select(User)).first()


def test_only_the_last_three_sessions_are_remembered(client, auth, db):
    ids = _sql_ids(db)
    for age, tid in enumerate(ids[:4], start=1):  # four sessions, each answered one SQL template
        _answered_session(db, _user(db).id, [tid], age)
    recent = interview._recent_template_ids(db, _user(db).id)
    assert set(recent) == set(ids[:3]) and ids[3] not in recent  # the oldest session is forgotten
    assert recent[ids[0]] == 0 and recent[ids[2]] == 2


def test_unanswered_questions_are_not_counted_as_used(client, auth, db):
    session = start(client, auth)
    assert interview._recent_template_ids(db, _user(db).id) == {}
    assert session["questions"]


def test_when_every_template_is_used_gemini_writes_a_new_question(client, auth, db, monkeypatch):
    ids = _sql_ids(db)
    _answered_session(db, _user(db).id, ids, 1)

    class Writer(LLMProvider):
        name = "gemini"

        def generate_json(self, prompt, schema, **context):
            return {"text": "A fresh generated SQL question for an entry-level analyst?", "keywords": ["join", "table"],
                    "follow_up": "Why?"}

    monkeypatch.setattr(ai, "get_provider", lambda: Writer())
    picked = interview.select_questions(db, "Backend Developer", [{"name": "SQL", "weight": 3}], [], [], 2, [], _user(db).id)
    sql = next(p for p in picked if p["skill"] == "SQL")
    assert sql["template_id"] not in ids
    assert db.get(QuestionTemplate, sql["template_id"]).source == "generated"


def test_when_every_template_is_used_and_gemini_is_off_the_oldest_is_asked_again(client, auth, db):
    ids = _sql_ids(db)
    _answered_session(db, _user(db).id, ids[:-1], 2)
    _answered_session(db, _user(db).id, [ids[-1]], 1)
    picked = interview.select_questions(db, "Backend Developer", [{"name": "SQL", "weight": 3}], [], [], 2, [], _user(db).id)
    sql = next(p for p in picked if p["skill"] == "SQL")
    assert sql["template_id"] in ids[:-1]  # not the newest one
    assert db.query(QuestionTemplate).filter_by(source="generated").count() == 0
