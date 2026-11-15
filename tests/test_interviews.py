"""The server-side interview engine. Tests use the rule-based provider (no network, no key);
Gemini is replaced by a fake that returns canned JSON."""

import pytest

from app.config import settings
from app.models import Domain, EvaluationCriterion, JobRole, QuestionTemplate, RoleSkill, ScoringRules, Skill
from app.services import ai
from app.services.ai.base import LLMProvider
from app.services.suitability import js_round
from tests.conftest import candidate_payload

SKILLS = ["React", "JavaScript", "CSS", "Python", "Communication"]
# (id, skill, type, followUp). Python has no template on purpose: it forces a generated question.
TEMPLATES = [
    ("q-react", "React", "technical", "Which hook would you use for that?"),
    ("q-js", "JavaScript", "technical", "Can you show a short example?"),
    ("q-css", "CSS", "technical", "Which breakpoints would you choose?"),
    ("q-comm", "Communication", "behavioral", "How did the other person react?"),
]
LONG_ANSWER = (
    "When I was building a project in my last semester I had to make the layout responsive. I decided to use "
    "flexbox and grid with a media query for each breakpoint, and for example I tested on mobile first. "
    "As a result the page worked well on every screen and I learned to plan the layout before writing CSS."
)


@pytest.fixture(autouse=True)
def rules_only(monkeypatch):
    monkeypatch.setattr(settings, "ai_provider", "rules")


@pytest.fixture
def library(db):
    db.add(Domain(id="web", name="Web"))
    for name in SKILLS:
        db.add(Skill(id=name.lower(), name=name, tip=f"Practise {name} every day.", aliases=[]))
    db.flush()
    db.add(JobRole(id="frontend", domain_id="web", title="Frontend Developer"))
    db.flush()
    for name, weight in [("React", 3), ("JavaScript", 3), ("CSS", 2), ("Python", 1)]:
        db.add(RoleSkill(role_id="frontend", skill_id=name.lower(), weight=weight))
    for qid, skill, qtype, follow in TEMPLATES:
        db.add(QuestionTemplate(
            id=qid, skill_id=skill.lower(), type=qtype, text=f"Tell me about {skill} in your own work.",
            keywords=["flexbox", "grid", "mobile", "breakpoint"], follow_up=follow,
        ))
    for key, weight, applies in [("technical", 2, "technical"), ("relevance", 2, "all"), ("completeness", 2, "all"),
                                 ("clarity", 1, "all"), ("communication", 1, "all"), ("star", 2, "behavioral")]:
        db.add(EvaluationCriterion(key=key, label=key, weight=weight, applies_to=applies))
    rules = db.get(ScoringRules, 1)
    rules.data = {"weakThreshold": 60, "weakMinSessions": 2, "followUpBelow": 55, "defaultQuestions": 5}
    db.commit()


@pytest.fixture
def auth(candidate):
    return {"Authorization": f"Bearer {candidate['token']}"}


@pytest.fixture
def other_auth(client):
    res = client.post("/api/auth/signup", json=candidate_payload(name="Bilal Ahmed", email="bilal@example.com"))
    return {"Authorization": f"Bearer {res.json()['token']}"}


def start(client, auth, **body):
    res = client.post("/api/interviews", headers=auth, json={"roleId": "frontend", "mode": "text", "count": 4, **body})
    assert res.status_code == 201, res.text
    return res.json()


def answer(client, auth, interview, question, text):
    return client.post(f"/api/interviews/{interview['id']}/answers", headers=auth,
                       json={"questionId": question["id"], "answer": text})


def sync_session(client, auth, session_id, skill_scores):
    """A finished session saved through POST /sessions (the same data an interview produces)."""
    answers = [{"questionId": None, "question": f"{s}?", "skill": s, "type": "technical", "score": sc, "criteria": {}}
               for s, sc in skill_scores.items()]
    res = client.post("/api/sessions", headers=auth, json={
        "id": session_id, "roleId": "frontend", "mode": "text", "score": 50, "answers": answers})
    assert res.status_code == 201, res.text


# ---------- selection ----------

def test_a_known_weakness_is_asked_first(client, auth, library):
    sync_session(client, auth, "s1", {"CSS": 40, "React": 85})
    sync_session(client, auth, "s2", {"CSS": 45, "React": 80})
    interview = start(client, auth, count=3)
    first = interview["questions"][0]
    assert interview["status"] == "in_progress"
    assert first["skill"] == "CSS" and first["reason"] == "weakness"
    assert [q["skill"] for q in interview["questions"]][1:] != ["CSS"]
    assert any(q["type"] == "behavioral" for q in interview["questions"])  # always one behavioural question


def test_cv_gaps_come_after_weaknesses_and_before_role_skills(client, auth, library):
    client.put("/api/profile", headers=auth, json={"skills": ["React", "JavaScript"], "cv": None, "shareWithEmployers": False})
    interview = start(client, auth, count=3)
    # CSS is a gap, and the lower-weighted role skill that the CV doesn't cover comes before React/JS
    assert interview["questions"][0]["skill"] == "CSS" and interview["questions"][0]["reason"] == "gap"


def test_a_skill_without_a_template_gets_a_generated_question(client, auth, library, db, monkeypatch):
    class Writer(LLMProvider):
        name = "gemini"

        def generate_json(self, prompt, schema, **context):
            return {"text": "How do you structure a small Python script that reads a CSV file?",
                    "keywords": ["Function", "csv", "csv"], "follow_up": "How would you test it?"}

    monkeypatch.setattr(ai, "get_provider", lambda: Writer())
    interview = start(client, auth, count=5)
    generated = next(q for q in interview["questions"] if q["skill"] == "Python")
    template = db.get(QuestionTemplate, generated["templateId"])
    assert template.source == "generated" and template.keywords == ["function", "csv"]
    assert generated["question"].startswith("How do you structure")


def test_offline_stand_in_question_is_not_saved(client, auth, library, db):
    interview = start(client, auth, count=5)
    python = next(q for q in interview["questions"] if q["skill"] == "Python")
    assert python["templateId"] is None
    assert db.query(QuestionTemplate).filter_by(source="generated").count() == 0


def test_start_needs_exactly_one_of_role_or_job(client, auth, library):
    assert client.post("/api/interviews", headers=auth, json={}).status_code == 422
    assert client.post("/api/interviews", headers=auth, json={"roleId": "frontend", "jobId": "x"}).status_code == 422
    assert client.post("/api/interviews", headers=auth, json={"roleId": "nope"}).status_code == 404


# ---------- answers ----------

def test_a_short_answer_triggers_a_follow_up_and_both_answers_are_stored(client, auth, library, db):
    interview = start(client, auth)
    question = interview["questions"][0]
    res = answer(client, auth, interview, question, "I use it a lot.")
    body = res.json()
    assert res.status_code == 200 and body["needsFollowUp"] is True
    assert body["provider"] == "rules" and 1 <= len(body["tips"]) <= 3
    assert body["followUp"]["question"]
    before = body["score"]

    follow = client.post(f"/api/interviews/{interview['id']}/answers/{body['answerId']}/follow-up", headers=auth,
                         json={"answer": LONG_ANSWER})
    assert follow.status_code == 200, follow.text
    assert follow.json()["score"] > before and follow.json()["needsFollowUp"] is False

    stored = client.get(f"/api/interviews/{interview['id']}", headers=auth).json()["questions"][0]
    assert stored["answer"] == "I use it a lot."
    assert stored["followUp"] == {"question": body["followUp"]["question"], "answer": LONG_ANSWER, "before": before}
    again = client.post(f"/api/interviews/{interview['id']}/answers/{body['answerId']}/follow-up", headers=auth,
                        json={"answer": LONG_ANSWER})
    assert again.status_code == 409


def test_template_follow_up_is_used_and_a_good_answer_needs_none(client, auth, library):
    interview = start(client, auth, count=5)  # all four role skills plus a behavioural question
    by_template = {q["templateId"]: q for q in interview["questions"]}
    short = answer(client, auth, interview, by_template["q-css"], "Yes.").json()
    assert short["followUp"]["question"] == "Which breakpoints would you choose?"
    assert answer(client, auth, interview, by_template["q-js"], LONG_ANSWER).json()["needsFollowUp"] is False


def test_blank_and_repeated_answers_are_rejected(client, auth, library):
    interview = start(client, auth)
    q = interview["questions"][0]
    assert answer(client, auth, interview, q, "   ").status_code == 422
    assert answer(client, auth, interview, q, LONG_ANSWER).status_code == 200
    assert answer(client, auth, interview, q, LONG_ANSWER).status_code == 409
    assert client.post(f"/api/interviews/{interview['id']}/answers", headers=auth,
                       json={"questionId": "nope", "answer": "hello there"}).status_code == 404


# ---------- Gemini: clamping, Python scoring, privacy ----------

class FakeGemini(LLMProvider):
    name = "gemini"

    def __init__(self, evaluation):
        self.evaluation, self.prompts = evaluation, []

    def generate_json(self, prompt, schema, **context):
        self.prompts.append(prompt)
        if context["task"] == "evaluate":
            return self.evaluation
        if context["task"] == "follow_up":
            return {"question": "What would you change next time?"}
        raise AssertionError(context["task"])


def test_gemini_scores_are_clamped_and_the_overall_is_computed_in_python(client, auth, candidate, library, monkeypatch):
    fake = FakeGemini({"technical": 150, "relevance": 80, "completeness": 60, "clarity": -5, "communication": 70.5,
                       "overall": 99, "tips": ["a", "b", "c", "d"], "needs_follow_up": False})
    monkeypatch.setattr(ai, "get_provider", lambda: fake)
    interview = start(client, auth)
    q = next(q for q in interview["questions"] if q["type"] == "technical")
    body = answer(client, auth, interview, q, LONG_ANSWER).json()
    assert body["provider"] == "gemini"
    assert body["criteria"] == {"technical": 100, "relevance": 80, "completeness": 60, "clarity": 0, "communication": 71}
    assert body["score"] == js_round((100 * 2 + 80 * 2 + 60 * 2 + 0 * 1 + 71 * 1) / 8) == 69  # weights from evaluation_criteria
    assert body["tips"] == ["a", "b", "c"] and body["needsFollowUp"] is False

    prompt = fake.prompts[-1]
    assert LONG_ANSWER in prompt and "Frontend Developer" in prompt
    for private in (candidate["user"]["name"], candidate["user"]["email"], "Ayesha", "example.com"):
        assert private not in prompt


def test_gemini_flag_and_low_completeness_both_ask_for_a_follow_up(client, auth, library, monkeypatch):
    monkeypatch.setattr(ai, "get_provider", lambda: FakeGemini(
        {"technical": 90, "relevance": 90, "completeness": 90, "clarity": 90, "communication": 90, "tips": [], "needs_follow_up": True}))
    interview = start(client, auth)
    q = next(q for q in interview["questions"] if q["type"] == "technical")
    body = answer(client, auth, interview, q, LONG_ANSWER).json()
    assert body["needsFollowUp"] is True and body["tips"]  # empty tips get a default
    assert body["followUp"]["question"]


def test_invalid_gemini_output_falls_back_to_rules(client, auth, library, monkeypatch):
    monkeypatch.setattr(ai, "get_provider", lambda: FakeGemini({"relevance": "high"}))
    interview = start(client, auth)
    q = next(q for q in interview["questions"] if q["type"] == "technical")
    assert answer(client, auth, interview, q, LONG_ANSWER).json()["provider"] == "rules"


# ---------- finish & history ----------

def test_finish_computes_the_session_score(client, auth, library):
    interview = start(client, auth, count=3)
    scores = []
    for q in interview["questions"][:2]:  # the third question is skipped
        scores.append(answer(client, auth, interview, q, LONG_ANSWER).json()["score"])
    res = client.post(f"/api/interviews/{interview['id']}/finish", headers=auth)
    body = res.json()
    assert res.status_code == 200 and body["status"] == "completed"
    assert body["score"] == js_round(sum(scores) / 2) and body["summary"]["answered"] == 2
    assert len(body["questions"]) == 2 and body["summary"]["providers"] == ["rules"]

    assert client.post(f"/api/interviews/{interview['id']}/finish", headers=auth).json()["score"] == body["score"]
    assert answer(client, auth, interview, interview["questions"][2], LONG_ANSWER).status_code == 409

    history = client.get("/api/interviews", headers=auth).json()
    assert [h["id"] for h in history] == [interview["id"]] and history[0]["answeredCount"] == 2


def test_finishing_with_no_answers_is_refused(client, auth, library):
    interview = start(client, auth)
    assert client.post(f"/api/interviews/{interview['id']}/finish", headers=auth).status_code == 409


# ---------- progress ----------

def test_a_skill_below_the_threshold_in_two_sessions_is_weak(client, auth, library):
    sync_session(client, auth, "s1", {"CSS": 40, "React": 85})
    first = client.get("/api/progress", headers=auth).json()
    assert not any(s["weak"] for s in first["skills"])  # one session isn't a pattern yet

    sync_session(client, auth, "s2", {"CSS": 50, "React": 90})
    progress = client.get("/api/progress", headers=auth).json()
    css = next(s for s in progress["skills"] if s["skill"] == "CSS")
    assert css["weak"] is True and css["avg"] == 45 and css["sessions"] == 2 and css["trend"] == 10
    assert next(s for s in progress["skills"] if s["skill"] == "React")["weak"] is False
    assert progress["weaknessProfile"] == [{"skill": "CSS", "avg": 45, "sessions": 2, "trend": 10, "tip": "Practise CSS every day."}]
    assert progress["sessionsCompleted"] == 2 and len(progress["scoreTrend"]) == 2


def test_unfinished_interviews_do_not_count_as_progress(client, auth, library):
    interview = start(client, auth)
    answer(client, auth, interview, interview["questions"][0], "Short.")
    assert client.get("/api/progress", headers=auth).json()["sessionsCompleted"] == 0


# ---------- access ----------

def test_a_candidate_cannot_read_or_change_another_candidates_interview(client, auth, other_auth, library):
    interview = start(client, auth)
    url = f"/api/interviews/{interview['id']}"
    q = interview["questions"][0]
    assert client.get(url, headers=other_auth).status_code == 404
    assert client.post(f"{url}/answers", headers=other_auth, json={"questionId": q["id"], "answer": "Hello there"}).status_code == 404
    assert client.post(f"{url}/finish", headers=other_auth).status_code == 404
    assert client.get("/api/interviews", headers=other_auth).json() == []
    assert client.get(url, headers=auth).status_code == 200


def test_interview_endpoints_are_for_signed_in_candidates(client, auth, library):
    assert client.get("/api/interviews").status_code == 401
    assert client.get("/api/progress").status_code == 401


# ---------- Gemini omits a criterion: retry, then fill only the gap from rules ----------

class SequencedGemini(FakeGemini):
    """Returns the queued evaluations in order, then repeats the last one."""

    def __init__(self, *evaluations):
        super().__init__(evaluations[0])
        self.queue = list(evaluations)

    def generate_json(self, prompt, schema, **context):
        if context["task"] == "evaluate":
            self.prompts.append(prompt)
            return self.queue.pop(0) if len(self.queue) > 1 else self.queue[0]
        return super().generate_json(prompt, schema, **context)


FULL = {"technical": 70, "relevance": 80, "completeness": 75, "clarity": 65, "communication": 60, "tips": ["a"]}
MISSING_TECH = {k: v for k, v in FULL.items() if k != "technical"}


def _technical(client, auth):
    interview = start(client, auth)
    return interview, next(q for q in interview["questions"] if q["type"] == "technical")


def test_a_missing_criterion_is_retried_with_a_stricter_prompt(client, auth, library, monkeypatch, caplog):
    fake = SequencedGemini(MISSING_TECH, FULL)
    monkeypatch.setattr(ai, "get_provider", lambda: fake)
    interview, q = _technical(client, auth)
    with caplog.at_level("WARNING"):
        body = answer(client, auth, interview, q, LONG_ANSWER).json()
    assert body["provider"] == "gemini" and body["criteria"]["technical"] == 70
    evals = [p for p in fake.prompts if "scoring one answer" in p]
    assert len(evals) == 2 and "MUST contain" not in evals[0] and "MUST contain" in evals[1]
    assert any("omitted criteria ['technical']" in r.message for r in caplog.records)
    assert LONG_ANSWER[:40] not in caplog.text  # answer text is never logged


def test_a_criterion_still_missing_after_the_retry_is_filled_from_rules_only(client, auth, library, monkeypatch, caplog):
    fake = SequencedGemini(MISSING_TECH, MISSING_TECH)
    monkeypatch.setattr(ai, "get_provider", lambda: fake)
    interview, q = _technical(client, auth)
    with caplog.at_level("WARNING"):
        body = answer(client, auth, interview, q, LONG_ANSWER).json()
    assert body["provider"] == "gemini+rules"
    c = body["criteria"]
    assert (c["relevance"], c["completeness"], c["clarity"], c["communication"]) == (80, 75, 65, 60)  # Gemini's kept
    assert isinstance(c["technical"], int) and 0 <= c["technical"] <= 100  # filled by the rules evaluator
    assert any("filling only those from the rules evaluator" in r.message for r in caplog.records)
    assert LONG_ANSWER[:40] not in caplog.text


def test_a_missing_required_criterion_is_handled_the_same_way(client, auth, library, monkeypatch):
    fake = SequencedGemini({k: v for k, v in FULL.items() if k != "clarity"})
    monkeypatch.setattr(ai, "get_provider", lambda: fake)
    interview, q = _technical(client, auth)
    body = answer(client, auth, interview, q, LONG_ANSWER).json()
    assert body["provider"] == "gemini+rules" and body["criteria"]["technical"] == 70
