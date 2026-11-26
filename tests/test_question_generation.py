"""Gemini writes the interview questions. The provider is a fake: no network, no key."""

import re
import threading

import pytest
from sqlalchemy import select

from app.config import settings
from app.models import CandidateProfile, JobRole, QuestionTemplate, SessionAnswer, User
from app.services import ai
from app.services.ai.base import AIUnavailable, InvalidAIResponse, LLMProvider
from app.services.security import hash_password
from tests.conftest import PASSWORD, bearer, sign_in
from tests.test_interviews import LONG_ANSWER, answer, auth, library, other_auth, start  # noqa: F401 (fixtures)

POINTS = ["state", "props", "rendering", "component"]
TEXTS = {
    "React": "In your shop project, how did you decide what belongs in React state?",
    "JavaScript": "How does JavaScript handle a slow network request without freezing the page?",
    "CSS": "How would you make a CSS card layout work on a narrow phone screen?",
    "Python": "Which Python data structure would you pick to count repeated words, and why?",
    "Communication": "Tell me about a time clear communication stopped a misunderstanding in your team.",
}


def written(skill: str, **changes) -> dict:
    return {"skill": skill, "text": TEXTS[skill], "keywords": [skill.lower(), *POINTS[:3]],
            "follow_up": f"What would you check next with {skill}?", **changes}


class FakeWriter(LLMProvider):
    """Writes a valid question for every skill unless `reply(skill)` says otherwise."""

    name = "gemini"

    def __init__(self, reply=written):
        self.reply, self.prompts, self.lock = reply, [], threading.Lock()

    def generate_json(self, prompt, schema, **context):
        if context["task"] != "question":
            raise AIUnavailable("only questions are faked")
        with self.lock:
            self.prompts.append(prompt)
        out = self.reply(context["skill"])
        if isinstance(out, Exception):
            raise out
        return out


@pytest.fixture(autouse=True)
def rules_only(monkeypatch):
    monkeypatch.setattr(settings, "ai_provider", "rules")


@pytest.fixture
def writer(monkeypatch):
    def use(reply=written) -> FakeWriter:
        fake = FakeWriter(reply)
        monkeypatch.setattr(ai, "get_provider", lambda: fake)
        return fake

    return use


def _generated(db):
    return db.scalars(select(QuestionTemplate).where(QuestionTemplate.status == "generated")).all()


def test_every_question_is_generated_saved_for_the_candidate_and_marked(client, auth, candidate, library, db, writer):
    fake = writer()
    interview = start(client, auth, count=5)
    questions = interview["questions"]
    assert len(questions) == 5 == len(fake.prompts) == len({q["skill"] for q in questions})
    assert any(q["type"] == "behavioral" for q in questions)
    for q in questions:
        assert q["question"] == TEXTS[q["skill"]] and q["questionOrigin"] == "generated"
        t = db.get(QuestionTemplate, q["templateId"])
        assert (t.status, t.source, t.candidate_id) == ("generated", "generated", candidate["user"]["id"])
        assert len(t.keywords) == 4 and t.follow_up
    assert {a.question_origin for a in db.scalars(select(SessionAnswer))} == {"generated"}


def test_the_generated_follow_up_is_the_one_asked(client, auth, library, writer):
    writer()
    interview = start(client, auth)
    q = interview["questions"][0]
    body = answer(client, auth, interview, q, "Yes.").json()
    assert body["followUp"]["question"] == f"What would you check next with {q['skill']}?"


@pytest.mark.parametrize("failure", [
    AIUnavailable("Gemini API error 429"),
    InvalidAIResponse("not JSON"),
    TimeoutError(),
    {"text": "too little"},
])
def test_a_failed_or_invalid_reply_falls_back_to_the_stored_template(client, auth, library, db, writer, failure):
    writer(lambda skill: failure)
    interview = start(client, auth, count=5)
    by_skill = {q["skill"]: q for q in interview["questions"]}
    assert by_skill["React"]["templateId"] == "q-react" and by_skill["CSS"]["templateId"] == "q-css"
    assert by_skill["Python"]["templateId"] is None  # no template: the offline stand-in
    assert {q["questionOrigin"] for q in interview["questions"]} == {"template"}
    assert not _generated(db)


def test_one_failed_slot_does_not_affect_the_others(client, auth, library, writer):
    writer(lambda skill: AIUnavailable("x") if skill == "CSS" else written(skill))
    origins = {q["skill"]: q["questionOrigin"] for q in start(client, auth, count=5)["questions"]}
    assert origins.pop("CSS") == "template" and set(origins.values()) == {"generated"}


def test_a_slow_provider_is_cut_off_at_the_deadline(client, auth, library, writer, monkeypatch):
    monkeypatch.setattr(settings, "ai_timeout_seconds", 0.5)
    release = threading.Event()

    def reply(skill):
        if skill == "React":
            release.wait(10)
        return written(skill)

    writer(reply)
    try:
        origins = {q["skill"]: q["questionOrigin"] for q in start(client, auth, count=5)["questions"]}
    finally:
        release.set()
    assert origins["React"] == "template" and origins["CSS"] == "generated"


@pytest.mark.parametrize("bad", [
    {"skill": "Python"},  # labelled as another skill
    {"text": "How do you plan your week when two deadlines clash?", "keywords": ["calendar", "priority", "plan", "time"],
     "follow_up": "What slipped last time?"},  # nothing about the skill
    {"text": "How would you " + "really " * 60 + "style this in CSS?"},  # 60 words or more
    {"text": "Write a CSS snippet that centres a box on the page."},  # coding
    {"text": "What is the output of this CSS selector example?"},  # code execution
    {"keywords": ["css", "grid", "flexbox"]},  # too few key points
    {"keywords": ["css", "a", "b", "c", "d", "e", "f"]},  # too many
    {"follow_up": ""},
    {"text": "Tell me about CSS in your own work!"},  # repeats the stored template
])
def test_off_skill_and_rule_breaking_output_is_rejected(client, auth, library, db, writer, bad):
    writer(lambda skill: written(skill, **bad) if skill == "CSS" else written(skill))
    interview = start(client, auth, count=5)
    css = next(q for q in interview["questions"] if q["skill"] == "CSS")
    assert css["templateId"] == "q-css" and css["questionOrigin"] == "template"
    assert not [t for t in _generated(db) if t.skill_id == "css"]


def test_a_question_from_a_recent_session_is_not_accepted_again(client, auth, library, writer):
    writer()
    first = start(client, auth, count=5)
    answer(client, auth, first, first["questions"][0], LONG_ANSWER)
    second = start(client, auth, count=5)
    assert {q["questionOrigin"] for q in second["questions"]} == {"template"}  # the writer repeated itself


def test_the_prompt_has_the_context_and_no_contact_data(client, auth, candidate, library, db, writer):
    private = ["Ayesha", "Khan", "ayesha@example.com", "0300-1234567", "+92 300 7654321", "House 12",
               "Rose Street", "linkedin.com/in/ayk", "ayk-dev", "second@mail.com"]
    profile = db.get(CandidateProfile, candidate["user"]["id"])  # created at sign-up
    profile.skills = ["React", "CSS", "ayesha@example.com", "Phone: 0300-1234567"]
    profile.parsed_cv = {
            "contact": {"name": "Ayesha Khan", "email": "second@mail.com", "phone": "+92 300 7654321",
                        "location": "House 12, Rose Street", "linkedin": "linkedin.com/in/ayk", "github": "ayk-dev"},
            "projects": [
                {"name": "Campus Shop by Ayesha Khan", "details": "Call 0300-1234567",
                 "tech": ["React", "ayesha@example.com"]},
                {"name": "Portfolio linkedin.com/in/ayk\nPhone: 0300-1234567\nAddress: House 12, Rose Street",
                 "tech": ["ayk-dev", "+92 300 7654321", "second@mail.com", "Vite"]},
            ],
    }
    db.get(JobRole, "frontend").responsibilities = ["Build pages people can use"]
    db.commit()

    fake = writer()
    first = start(client, auth, count=5)
    react = next(q for q in first["questions"] if q["skill"] == "React")
    answer(client, auth, first, react, "I keep state in the component and pass props down. Mail ayesha@example.com.")
    fake.prompts.clear()
    start(client, auth, count=5)

    everything = "\n".join(fake.prompts)
    for value in private:
        assert value.lower() not in everything.lower(), value
    assert not re.search(r"[\w.+-]+@[\w-]+\.\w+|\d{4}[- ]\d{7}", everything)
    assert "Mail" not in everything and "pass props down" not in everything  # answer text is not sent

    prompt = next(p for p in fake.prompts if 'tests the skill "React"' in p)
    for expected in ("Frontend Developer", "Build pages people can use", "Skills on the candidate's CV: React, CSS",
                     "Campus Shop by", "(React)", "Vite", "Difficulty: medium", "under 60 words",
                     "Tell me about React in your own work.", react["question"]):
        assert expected in prompt, expected
    missed = re.search(r"missed in earlier answers on this skill: (.*)", prompt).group(1)
    assert "rendering" in missed and "props" not in missed  # only what the answer left out


def test_generated_questions_are_not_shown_or_asked_to_other_candidates(client, auth, other_auth, library, writer,
                                                                      monkeypatch):
    writer()
    ids = {q["templateId"] for q in start(client, auth, count=5)["questions"]}
    monkeypatch.setattr(ai, "get_provider", lambda: ai.RuleBasedProvider())

    theirs = start(client, other_auth, count=5)
    assert ids.isdisjoint({q["templateId"] for q in theirs["questions"]})
    config = client.get("/api/config", headers=other_auth).json()
    assert ids.isdisjoint({q["id"] for q in config["questions"]})


def test_an_admin_reviews_and_approves_a_generated_question(client, auth, other_auth, library, db, writer, monkeypatch):
    writer()
    python = next(q for q in start(client, auth, count=5)["questions"] if q["skill"] == "Python")
    monkeypatch.setattr(ai, "get_provider", lambda: ai.RuleBasedProvider())
    db.add(User(id="admin-1", role="admin", name="Admin", email="admin@example.com",
                password_hash=hash_password(PASSWORD)))
    db.commit()
    admin = bearer(sign_in(client, "admin@example.com", role="admin")["token"])
    url = f"/api/admin/questions/{python['templateId']}"

    row = client.get("/api/admin/questions?skill=Python", headers=admin).json()[0]
    assert row["status"] == "generated" and row["source"] == "generated"
    assert client.post(f"{url}/approve", headers=auth).status_code == 403

    edit = {k: row[k] for k in ("skill", "type", "text", "keywords", "followUp", "difficulty")}
    edited = client.put(url, headers=admin, json={**edit, "text": "Which Python structure counts words, and why?"})
    assert edited.status_code == 200 and edited.json()["status"] == "generated"  # editing does not approve

    approved = client.post(f"{url}/approve", headers=admin)
    assert approved.status_code == 200 and approved.json()["status"] == "approved"
    db.expire_all()
    assert db.get(QuestionTemplate, python["templateId"]).candidate_id is None

    asked = next(q for q in start(client, other_auth, count=5)["questions"] if q["skill"] == "Python")
    assert asked["templateId"] == python["templateId"] and asked["questionOrigin"] == "template"
    assert client.delete(url, headers=admin).status_code == 204
    assert client.post("/api/admin/questions/nope/approve", headers=admin).status_code == 404
