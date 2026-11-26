"""The shipped configuration (scripts/seed_config.py): its data, and what running it does to a database."""

import re
from collections import Counter
from datetime import timedelta

import pytest
from sqlalchemy import update

from app.config import settings
from app.models import (
    Domain, InterviewSession, Job, JobRole, JobSkill, QuestionTemplate, RoleSkill, SessionAnswer, Skill, User,
)
from app.services import ai, interview
from app.services.ai.base import AIUnavailable, LLMProvider
from app.services.ai.prompts import question_prompt
from app.services.catalog import load_config
from app.services.security import hash_password
from scripts import seed_config as cfg

SKILL_NAMES = [s[0] for s in cfg.SKILLS]
CODING = re.compile(r"\b(write (a |the |some )?(code|function|program|script|query)|implement|algorithm|code snippet|"
                    r"output of|what does this code|run this|leetcode|big-o)\b", re.I)


@pytest.fixture(autouse=True)
def rules_only(monkeypatch):
    monkeypatch.setattr(settings, "ai_provider", "rules")


# ---------- the data ----------

def test_four_domains_and_fifteen_roles():
    assert len(cfg.DOMAINS) == 4 and len(cfg.ROLES) == 15
    assert Counter(r[2] for r in cfg.ROLES) == {"tech": 5, "business": 3, "marketing": 3, "hrfin": 4}
    assert {r[2] for r in cfg.ROLES} == {d[0] for d in cfg.DOMAINS}


def test_names_are_unique():
    titles = [r[1].lower() for r in cfg.ROLES]
    assert len(set(titles)) == len(titles)
    assert len({r[0] for r in cfg.ROLES}) == len(cfg.ROLES)
    assert len({n.lower() for n in SKILL_NAMES}) == len(SKILL_NAMES)
    assert len({cfg.slug(n) for n in SKILL_NAMES}) == len(SKILL_NAMES)
    assert len({q[0] for q in cfg.QUESTIONS}) == len(cfg.QUESTIONS)
    assert all(len(cfg.slug(n)) <= 40 for n in SKILL_NAMES) and all(len(q[0]) <= 40 for q in cfg.QUESTIONS)


@pytest.mark.parametrize("role", cfg.ROLES, ids=[r[1] for r in cfg.ROLES])
def test_every_role_has_five_to_seven_weighted_skills_and_responsibilities(role):
    _, title, _, skills, duties = role
    names = [s for s, _ in skills]
    assert 5 <= len(skills) <= 7, title
    assert len(set(names)) == len(names), title
    assert all(w in (1, 2, 3) for _, w in skills), title
    assert set(names) <= set(SKILL_NAMES), title
    assert 3 <= len(duties) <= 6 and all(0 < len(d) <= 60 for d in duties), title


def test_every_skill_has_aliases_tip_related_and_a_technical_question():
    technical = {q[1] for q in cfg.QUESTIONS if q[2] == "technical"}
    for name, aliases, related, tip in cfg.SKILLS:
        assert aliases and all(a == a.lower().strip() and a for a in aliases), name
        assert len(set(aliases)) == len(aliases), name
        assert related and set(related) <= set(SKILL_NAMES) and name not in related, name
        assert tip.strip(), name
        assert name in technical, name
    for _, skill, type_, text, keywords, follow_up in cfg.QUESTIONS:
        assert skill in SKILL_NAMES and type_ in ("technical", "behavioral")
        assert len(text) >= 10 and keywords and follow_up.strip(), text
        assert all(k == k.lower() for k in keywords), text


def test_shared_behavioural_questions_exist():
    behavioural = {q[1] for q in cfg.QUESTIONS if q[2] == "behavioral"}
    assert behavioural == {"Communication", "Teamwork", "Problem solving", "Time management", "Leadership"}


def test_no_question_asks_for_code():
    for q in cfg.QUESTIONS:
        assert not CODING.search(q[3]), q[3]
        assert not CODING.search(q[5]), q[5]


# ---------- running it ----------

def _count(db, model):
    return db.query(model).count()


def test_apply_loads_everything_and_is_repeatable(db):
    cfg.apply(db)
    db.commit()
    assert _count(db, Domain) == 4 and _count(db, JobRole) == 15
    assert _count(db, Skill) == len(cfg.SKILLS) and _count(db, QuestionTemplate) == len(cfg.QUESTIONS)
    for role in db.query(JobRole):
        assert 5 <= len(role.skills) <= 7 and role.responsibilities and role.active
        assert all(1 <= link.weight <= 3 for link in role.skills)

    again = cfg.apply(db)
    db.commit()
    assert again["skills_added"] == again["roles_added"] == again["questions_added"] == 0
    assert _count(db, JobRole) == 15 and _count(db, Skill) == len(cfg.SKILLS)
    assert _count(db, QuestionTemplate) == len(cfg.QUESTIONS)
    assert _count(db, RoleSkill) == sum(len(r[3]) for r in cfg.ROLES)


def test_old_data_is_handled_and_nothing_important_is_deleted(db):
    db.add(Domain(id="tech", name="Technology"))
    db.add_all([Skill(id="react", name="React", aliases=["react"], related=[]),
                Skill(id="node-js", name="Node.js", aliases=["node"], related=[]),
                Skill(id="old-used", name="Old Used", aliases=["old used"], related=[]),
                Skill(id="old-answered", name="Old Answered", aliases=["old answered"], related=[])])
    db.add(User(id="emp-1", role="employer", name="Hira", email="hr@example.com", password_hash=hash_password("x")))
    db.add(User(id="cand-1", role="candidate", name="Ayesha", email="a@example.com", password_hash=hash_password("x")))
    db.flush()
    db.add_all([JobRole(id="frontend", title="Frontend Developer", domain_id="tech"),
                JobRole(id="legacy", title="Legacy Role", domain_id="tech"),
                JobRole(id="legacy-job", title="Legacy With Job", domain_id="tech")])
    db.flush()
    db.add(RoleSkill(role_id="frontend", skill_id="node-js", weight=2))
    db.add(QuestionTemplate(id="q1", skill_id="react", type="technical", text="An old demo question text", keywords=[]))
    db.add(Job(id="job-1", employer_id="emp-1", company="Northstar", title="Junior Dev", role_id="legacy-job", location="Lahore", mode="Remote", level="Entry level", type="Full-time"))
    db.flush()
    db.add(JobSkill(job_id="job-1", skill_id="old-used", weight=2))
    session = InterviewSession(id="s-1", candidate_id="cand-1", role_id="legacy", mode="text", score=50)
    session.answers.append(SessionAnswer(id="ans-1", skill_id="old-answered", position=0, question="Why?", type="technical"))
    db.add(session)
    db.commit()

    report = cfg.apply(db)
    db.commit()

    assert db.get(User, "emp-1") and db.get(User, "cand-1") and db.get(Job, "job-1")
    assert db.get(InterviewSession, "s-1") and db.get(SessionAnswer, "ans-1").skill_id == "old-answered"
    frontend = db.get(JobRole, "frontend")  # same id, new title data, skills and weights
    assert frontend.responsibilities and frontend.active
    assert {l.skill.name: l.weight for l in frontend.skills}["React"] == 3
    assert "Node.js" not in {l.skill.name for l in frontend.skills}
    assert db.get(Skill, "old-used") and db.get(Skill, "old-answered") and db.get(Skill, "node-js") is None
    assert set(report["skills_kept"]) == {"Old Used", "Old Answered"} and report["skills_deleted"] == ["Node.js"]
    assert db.get(JobRole, "legacy").active is False  # inactive, not deleted
    assert db.get(JobRole, "legacy-job").active is True  # a job still uses it
    assert db.get(QuestionTemplate, "q1") is None and _count(db, QuestionTemplate) == len(cfg.QUESTIONS)


def test_admin_edited_demo_question_is_kept(db):
    db.add(Skill(id="react", name="React", aliases=["react"], related=[]))
    db.flush()
    db.add(QuestionTemplate(id="q4", skill_id="react", type="technical", text="Edited by an admin later", keywords=[]))
    db.commit()
    created = db.get(QuestionTemplate, "q4").created_at
    db.execute(update(QuestionTemplate).where(QuestionTemplate.id == "q4").values(updated_at=created + timedelta(days=1)))
    db.commit()
    cfg.apply(db)
    db.commit()
    assert db.get(QuestionTemplate, "q4") is not None


def test_public_config_hides_inactive_roles_and_shows_responsibilities(db):
    cfg.apply(db)
    db.add(JobRole(id="legacy", title="Legacy Role", domain_id="tech", active=False))
    db.commit()
    roles = {r["title"]: r for r in load_config(db)["roles"]}
    assert "Legacy Role" not in roles and len(roles) == 15
    assert roles["Data Analyst"]["responsibilities"] == ["Clean data", "Build reports and dashboards", "Find trends", "Explain findings"]


# ---------- responsibilities reach the question prompt ----------

def test_prompt_includes_responsibilities():
    prompt = question_prompt("Data Analyst", ["Clean data", "Find trends"], "SQL", "technical", "easy", [], [], [], [], [])
    assert "- Clean data" in prompt and "- Find trends" in prompt and "No coding" in prompt and "Difficulty: easy" in prompt


def test_generated_questions_get_the_role_responsibilities(db, monkeypatch):
    seen = []

    class Recorder(LLMProvider):
        name = "gemini"

        def generate_json(self, prompt, schema, **context):
            seen.append(prompt)
            raise AIUnavailable("recorded only")

    monkeypatch.setattr(ai, "get_provider", lambda: Recorder())
    db.add(Skill(id="sql", name="SQL", aliases=["sql"], related=[]))
    db.commit()
    interview.select_questions(db, "Data Analyst", [{"name": "SQL", "weight": 3}], [], [], 1, ["Clean data", "Find trends"])
    assert seen and "- Clean data" in seen[0]
