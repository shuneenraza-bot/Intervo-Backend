"""Employer side: config, jobs, applications and the ranked candidate list."""

from datetime import datetime, timedelta, timezone

import pytest

from app.db import new_id
from app.models import (
    CandidateProfile,
    Domain,
    EvaluationCriterion,
    InterviewSession,
    JobRole,
    RoleSkill,
    ScoringRules,
    SessionAnswer,
    Skill,
)
from app.services.matching import cv_fit
from tests.conftest import candidate_payload, employer_payload, signup_full

RULES = {
    "weakThreshold": 60, "weakMinSessions": 2, "followUpBelow": 55, "defaultQuestions": 5,
    "faceThreshold": 0.55,
}
# name -> related skills (same as the seed data)
SKILLS = {
    "React": ["JavaScript"], "JavaScript": ["TypeScript", "React"], "TypeScript": ["JavaScript"],
    "CSS": ["HTML"], "HTML": ["CSS"], "Git": [], "Testing": [], "Communication": ["Teamwork"],
}
# In the order the API returns job skills: heaviest weight first, then by name.
JOB_SKILLS = [
    {"name": "JavaScript", "weight": 3}, {"name": "React", "weight": 3}, {"name": "CSS", "weight": 2},
    {"name": "Git", "weight": 1}, {"name": "Testing", "weight": 1},
]
JOB = {
    "title": "Junior Frontend Developer", "roleId": "frontend", "description": "Build web pages.",
    "location": "Lahore", "mode": "Remote", "level": "Entry level", "type": "Full-time", "status": "open",
    "skills": JOB_SKILLS, "success": {"minMatch": 60, "notes": "Explains component design."},
}
# Ayesha from the demo data: (days ago, [(skill, score)])
AYESHA_SKILLS = ["React", "JavaScript", "HTML", "CSS", "Git", "Communication"]
AYESHA_SESSIONS = [
    (12, [("React", 64), ("JavaScript", 70), ("CSS", 58), ("Communication", 66)]),
    (5, [("React", 76), ("CSS", 62), ("Testing", 48), ("Communication", 74)]),
    (1, [("React", 82), ("JavaScript", 79), ("Testing", 55), ("Git", 72)]),
]
SECRET_ANSWER = "My private answer text that employers must never see."


def slug(name: str) -> str:
    return name.lower().replace(" ", "-")


@pytest.fixture(autouse=True)
def catalog(db):
    """Skill library, one role, criteria and full scoring rules."""
    db.get(ScoringRules, 1).data = RULES
    db.add(Domain(id="tech", name="Technology"))
    db.add_all(Skill(id=slug(n), name=n, aliases=[n.lower()], related=r, tip="") for n, r in SKILLS.items())
    db.add(EvaluationCriterion(key="relevance", label="Relevance", weight=2, applies_to="all", enabled=True))
    db.flush()
    db.add(JobRole(id="frontend", title="Frontend Developer", domain_id="tech"))
    db.flush()
    db.add_all([RoleSkill(role_id="frontend", skill_id="react", weight=3), RoleSkill(role_id="frontend", skill_id="css", weight=2)])
    db.commit()


def signup(client, payload) -> tuple[dict, dict]:
    """Returns (user, auth headers)."""
    body = signup_full(client, payload)
    return body["user"], {"Authorization": f"Bearer {body['token']}"}


@pytest.fixture
def employer(client):
    return signup(client, employer_payload())


@pytest.fixture
def other_employer(client):
    return signup(client, employer_payload(email="hr@rival.example.com", company="Rival Ltd", name="Omar Rival"))


@pytest.fixture
def ayesha(client, db):
    """A candidate with CV skills, a parsed CV and three practice sessions."""
    user, headers = signup(client, candidate_payload())
    profile = db.get(CandidateProfile, user["id"])
    profile.skills = AYESHA_SKILLS
    profile.cv = {
        "contact": {"name": "Ayesha Khan", "email": "ayesha@example.com", "phone": "0300-1234567"},
        "education": [{"degree": "BS Computer Science", "institution": "UOG", "dates": "2021-2025", "score": ""}],
        "experience": [], "experienceYears": 1.5,
        "projects": [{"name": "Portfolio", "details": "", "tech": ["React"]}, {"name": "Shop", "details": "", "tech": []}],
    }
    db.commit()
    add_sessions(db, user["id"], AYESHA_SESSIONS)
    return user, headers


def add_sessions(db, user_id, sessions):
    now = datetime.now(timezone.utc)
    for days, scores in sessions:
        db.add(InterviewSession(
            id=new_id("s"), candidate_id=user_id, role_id="frontend", mode="video",
            date=now - timedelta(days=days), score=round(sum(s for _, s in scores) / len(scores)),
            answers=[
                SessionAnswer(
                    id=new_id("ans"), skill_id=slug(skill), position=i, question=f"About {skill}?", type="technical",
                    score=score, criteria={"relevance": score}, answer=SECRET_ANSWER,
                    indicators={"eyeContact": 80}, follow_up={"question": "More?", "answer": SECRET_ANSWER, "before": 40},
                )
                for i, (skill, score) in enumerate(scores)
            ],
        ))
    db.commit()


def create_job(client, headers, **overrides) -> dict:
    res = client.post("/api/jobs", json={**JOB, **overrides}, headers=headers)
    assert res.status_code == 201, res.text
    return res.json()


# ---------- CV fit (pure function) ----------

def test_cv_fit_matches_frontend_skill_match():
    skill_config = [{"name": n, "related": r} for n, r in SKILLS.items()]
    fit = cv_fit({"skills": JOB_SKILLS, "success": JOB["success"]}, {"skills": AYESHA_SKILLS}, skill_config)
    # React, JavaScript, CSS, Git matched (9 of 10 weight); Testing missing
    assert fit["percentage"] == 90
    assert [s["name"] for s in fit["matched"]] == ["JavaScript", "React", "CSS", "Git"]
    assert [s["name"] for s in fit["missing"]] == ["Testing"]
    assert fit["partial"] == [] and fit["checks"] == []
    assert fit["meetsCriteria"] is True  # 90 >= minMatch 60
    assert set(fit) == {"matched", "partial", "missing", "percentage", "checks", "meetsCriteria"}


def test_cv_fit_partial_match_and_minimum():
    skill_config = [{"name": n, "related": r} for n, r in SKILLS.items()]
    fit = cv_fit({"skills": JOB_SKILLS, "success": JOB["success"]}, {"skills": ["TypeScript", "CSS"]}, skill_config)
    assert [(p["name"], p["via"]) for p in fit["partial"]] == [("JavaScript", "TypeScript")]
    assert fit["percentage"] == 35  # CSS 2 + half of JavaScript 3, out of 10
    assert fit["meetsCriteria"] is False  # 35 < 60
    assert cv_fit({"skills": JOB_SKILLS, "success": {}}, None, skill_config)["meetsCriteria"] is True  # no minimum set


# ---------- config ----------

def test_config_requires_sign_in_and_has_frontend_shape(client, employer):
    assert client.get("/api/config").status_code == 401
    res = client.get("/api/config", headers=employer[1])
    assert res.status_code == 200
    config = res.json()
    assert set(config) == {"domains", "skills", "roles", "questions", "criteria", "rules"}
    assert config["domains"] == [{"id": "tech", "name": "Technology"}]
    assert {"name": "React", "aliases": ["react"], "related": ["JavaScript"], "tip": ""} in config["skills"]
    assert config["roles"] == [{"id": "frontend", "title": "Frontend Developer", "domainId": "tech",
                                "skills": [{"name": "React", "weight": 3}, {"name": "CSS", "weight": 2}]}]
    assert config["criteria"] == [{"key": "relevance", "label": "Relevance", "weight": 2, "appliesTo": "all", "enabled": True}]
    assert "suitability" not in config["rules"]


# ---------- jobs ----------

def test_employer_creates_and_edits_job(client, employer):
    user, headers = employer
    job = create_job(client, headers)
    assert job["id"].startswith("job-")
    assert job["employerId"] == user["id"]
    assert job["company"] == "Northstar Digital"  # from the account, not the body
    assert isinstance(job["createdAt"], int)
    assert job["skills"] == JOB_SKILLS
    assert job["success"] == JOB["success"]

    edited = {**job, "title": "Frontend Developer", "skills": [{"name": "React", "weight": 2}, {"name": "HTML", "weight": 1}],
              "success": {"minMatch": 50, "notes": ""}}
    res = client.put(f"/api/jobs/{job['id']}", json=edited, headers=headers)
    assert res.status_code == 200, res.text
    assert res.json()["title"] == "Frontend Developer"
    assert res.json()["skills"] == [{"name": "React", "weight": 2}, {"name": "HTML", "weight": 1}]
    assert res.json()["success"] == {"minMatch": 50, "notes": ""}  # no interview score on a job

    res = client.patch(f"/api/jobs/{job['id']}/status", json={"status": "closed"}, headers=headers)
    assert res.status_code == 200 and res.json()["status"] == "closed"


def test_job_validation_and_roles(client, employer, ayesha):
    headers = employer[1]
    assert client.post("/api/jobs", json=JOB, headers=ayesha[1]).status_code == 403  # candidates can't post
    assert client.post("/api/jobs", json=JOB).status_code == 401
    res = client.post("/api/jobs", json={**JOB, "skills": [{"name": "Juggling", "weight": 2}]}, headers=headers)
    assert res.status_code == 422 and "Juggling" in res.json()["detail"]
    assert client.post("/api/jobs", json={**JOB, "skills": [{"name": "React", "weight": 5}]}, headers=headers).status_code == 422
    assert client.post("/api/jobs", json={**JOB, "roleId": "nope"}, headers=headers).status_code == 422


def test_job_list_visibility_and_applicant_counts(client, employer, other_employer, ayesha):
    open_job = create_job(client, employer[1])
    closed_job = create_job(client, employer[1], title="Old posting", status="closed")
    rival_closed = create_job(client, other_employer[1], title="Rival closed", status="closed")
    assert client.post(f"/api/jobs/{open_job['id']}/apply", json={"consent": True}, headers=ayesha[1]).status_code == 201

    mine = client.get("/api/jobs", headers=employer[1]).json()
    by_id = {j["id"]: j for j in mine["jobs"]}
    assert set(by_id) == {open_job["id"], closed_job["id"]}  # own closed job yes, the rival's no
    assert by_id[open_job["id"]]["applicantCount"] == 1
    assert by_id[closed_job["id"]]["applicantCount"] == 0
    assert [a["jobId"] for a in mine["applications"]] == [open_job["id"]]

    seen = client.get("/api/jobs", headers=ayesha[1]).json()
    assert [j["id"] for j in seen["jobs"]] == [open_job["id"]]  # open jobs only
    assert seen["jobs"][0]["applicantCount"] is None
    assert len(seen["applications"]) == 1 and seen["applications"][0]["candidateId"] == ayesha[0]["id"]

    rival = client.get("/api/jobs", headers=other_employer[1]).json()
    assert {j["id"] for j in rival["jobs"]} == {open_job["id"], rival_closed["id"]}
    assert rival["applications"] == []  # no access to another employer's applicants
    assert next(j for j in rival["jobs"] if j["id"] == open_job["id"])["applicantCount"] is None


# ---------- applications ----------

def test_apply_withdraw_and_status(client, db, employer, ayesha):
    user, headers = ayesha
    db.get(CandidateProfile, user["id"]).share_with_employers = False
    db.commit()
    job = create_job(client, employer[1])
    url = f"/api/jobs/{job['id']}/apply"

    res = client.post(url, json={"consent": True}, headers=headers)
    assert res.status_code == 201, res.text
    application = res.json()
    assert application["jobId"] == job["id"] and application["candidateId"] == user["id"]
    assert application["consent"] is True and application["status"] == "applied"
    assert isinstance(application["date"], int)
    db.expire_all()
    assert db.get(CandidateProfile, user["id"]).share_with_employers is True  # consent turns sharing on

    assert client.post(url, json={"consent": True}, headers=headers).status_code == 409  # already applied
    assert client.post(url, json={"consent": True}, headers=employer[1]).status_code == 403  # employers can't apply

    # the job owner moves it through the pipeline (API.md path and the /status alias)
    url_status = f"/api/applications/{application['id']}/status"
    res = client.patch(url_status, json={"status": "shortlisted"}, headers=employer[1])
    assert res.status_code == 200 and res.json()["status"] == "shortlisted"
    res = client.patch(url_status, json={"status": "not_progressing"}, headers=employer[1])
    assert res.status_code == 200 and res.json()["status"] == "not_progressing"
    assert client.patch(url_status, json={"status": "hired"}, headers=employer[1]).status_code == 422
    assert client.patch(url_status, json={"status": "accepted"}, headers=employer[1]).status_code == 422  # only the candidate accepts
    assert client.patch(url_status, json={"status": "shortlisted"}, headers=headers).status_code == 403

    assert client.delete(url, headers=headers).status_code == 204
    assert client.get("/api/jobs", headers=headers).json()["applications"] == []

    client.patch(f"/api/jobs/{job['id']}/status", json={"status": "closed"}, headers=employer[1])
    assert client.post(url, json={"consent": True}, headers=headers).status_code == 404  # closed
    assert client.post("/api/jobs/job-missing/apply", json={"consent": True}, headers=headers).status_code == 404


# ---------- ranked candidates ----------

def test_employer_sees_only_the_cv_match(client, employer, ayesha):
    job = create_job(client, employer[1], description="We need 1+ years of experience. Bachelor degree in Computer Science.")
    assert client.post(f"/api/jobs/{job['id']}/apply", json={"consent": True}, headers=ayesha[1]).status_code == 201

    res = client.get(f"/api/jobs/{job['id']}/candidates", headers=employer[1])
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["job"]["id"] == job["id"] and body["hidden"] == 0
    assert set(body) == {"job", "hidden", "candidates"}
    assert len(body["candidates"]) == 1

    entry = body["candidates"][0]
    # Exactly these keys: no sessions, profile, fit/factors, evidence or any interview score.
    assert set(entry) == {"application", "candidate", "cvSummary", "match"}
    assert entry["candidate"] == {"id": ayesha[0]["id"], "name": "Ayesha Khan"}  # no email or phone before they accept
    assert entry["application"]["consent"] is True

    match = entry["match"]
    assert set(match) == {"matched", "partial", "missing", "percentage", "checks", "meetsCriteria"}
    assert match["percentage"] == 90
    assert match["matched"] == [
        {"name": "JavaScript", "weight": 3}, {"name": "React", "weight": 3},
        {"name": "CSS", "weight": 2}, {"name": "Git", "weight": 1},
    ]
    assert match["missing"] == [{"name": "Testing", "weight": 1}]
    assert match["meetsCriteria"] is True
    assert match["checks"] == [
        {"key": "experience", "label": "Experience", "required": "1+ years", "actual": "1.5 years", "met": True},
        {"key": "education", "label": "Education", "required": "Bachelor degree in Computer Science",
         "actual": "BS Computer Science", "met": True},
    ]
    assert entry["cvSummary"] == {"topDegree": "BS Computer Science", "experienceYears": 1.5, "projectCount": 2}

    # Her three practice sessions exist in the database, but nothing from them is in the response.
    assert SECRET_ANSWER not in res.text
    lowered = res.text.lower()
    for word in ("session", "interview", "evidence", "consistency", "suitability", "avgscore", "factors", "perf",
                 "weak", "minscore", "indicators", "followup", "trend", "eyecontact"):
        assert word not in lowered, word
    for forbidden in ("face", "template", "passwordHash", "password_hash", "0300-1234567", "phone"):
        assert forbidden not in res.text


def test_requirement_checks_fail_when_cv_falls_short(client, employer, ayesha):
    job = create_job(client, employer[1], description="Requires 5+ years. Master degree preferred.")
    client.post(f"/api/jobs/{job['id']}/apply", json={"consent": True}, headers=ayesha[1])
    checks = client.get(f"/api/jobs/{job['id']}/candidates", headers=employer[1]).json()["candidates"][0]["match"]["checks"]
    assert [(c["key"], c["met"]) for c in checks] == [("experience", False), ("education", False)]


def test_candidates_are_ranked_by_cv_match(client, db, employer, ayesha):
    job = create_job(client, employer[1])
    bilal, bilal_headers = signup(client, candidate_payload(email="bilal@example.com", name="Bilal Ahmed"))
    db.get(CandidateProfile, bilal["id"]).skills = ["TypeScript", "CSS"]
    db.commit()
    # Bilal has excellent interview scores, which must not help him: only the CV match ranks.
    add_sessions(db, bilal["id"], [(3, [("React", 99), ("CSS", 99)])])

    # the weaker CV applies first, so order must come from the match
    for headers in (bilal_headers, ayesha[1]):
        assert client.post(f"/api/jobs/{job['id']}/apply", json={"consent": True}, headers=headers).status_code == 201

    body = client.get(f"/api/jobs/{job['id']}/candidates", headers=employer[1]).json()
    assert [c["candidate"]["name"] for c in body["candidates"]] == ["Ayesha Khan", "Bilal Ahmed"]
    assert [c["match"]["percentage"] for c in body["candidates"]] == [90, 35]
    weaker = body["candidates"][1]["match"]
    assert [(p["name"], p["via"]) for p in weaker["partial"]] == [("JavaScript", "TypeScript")]
    assert weaker["meetsCriteria"] is False  # 35 < minMatch 60
    assert body["candidates"][1]["cvSummary"] is None  # no CV uploaded


def test_job_has_no_interview_score_field(client, employer):
    job = create_job(client, employer[1])
    assert job["success"] == {"minMatch": 60, "notes": "Explains component design."}
    assert "minScore" not in client.get("/api/jobs", headers=employer[1]).text


def test_another_employer_gets_403(client, employer, other_employer, ayesha):
    job = create_job(client, employer[1])
    application = client.post(f"/api/jobs/{job['id']}/apply", json={"consent": True}, headers=ayesha[1]).json()
    rival = other_employer[1]

    res = client.get(f"/api/jobs/{job['id']}/candidates", headers=rival)
    assert res.status_code == 403
    assert "Ayesha" not in res.text
    assert client.put(f"/api/jobs/{job['id']}", json={**JOB, "title": "Hijacked"}, headers=rival).status_code == 403
    assert client.patch(f"/api/jobs/{job['id']}/status", json={"status": "closed"}, headers=rival).status_code == 403
    assert client.patch(f"/api/applications/{application['id']}/status", json={"status": "shortlisted"}, headers=rival).status_code == 403

    # candidates can't read the list either, and nothing was changed
    assert client.get(f"/api/jobs/{job['id']}/candidates", headers=ayesha[1]).status_code == 403
    assert client.get(f"/api/jobs/{job['id']}/candidates").status_code == 401
    assert client.get("/api/jobs/job-missing/candidates", headers=employer[1]).status_code == 404
    mine = client.get("/api/jobs", headers=employer[1]).json()
    assert mine["jobs"][0]["title"] == JOB["title"] and mine["jobs"][0]["status"] == "open"
    assert mine["applications"][0]["status"] == "applied"


def test_applicant_without_consent_is_hidden(client, db, employer, ayesha):
    job = create_job(client, employer[1])
    assert client.post(f"/api/jobs/{job['id']}/apply", json={"consent": False}, headers=ayesha[1]).status_code == 201

    res = client.get(f"/api/jobs/{job['id']}/candidates", headers=employer[1])
    assert res.status_code == 200
    assert res.json()["candidates"] == []
    assert res.json()["hidden"] == 1
    assert "Ayesha" not in res.text and ayesha[0]["id"] not in res.text


def test_applicant_who_stopped_sharing_is_hidden(client, db, employer, ayesha):
    """consent=true on the application is not enough once share_with_employers is off."""
    job = create_job(client, employer[1])
    assert client.post(f"/api/jobs/{job['id']}/apply", json={"consent": True}, headers=ayesha[1]).status_code == 201
    assert len(client.get(f"/api/jobs/{job['id']}/candidates", headers=employer[1]).json()["candidates"]) == 1

    db.get(CandidateProfile, ayesha[0]["id"]).share_with_employers = False
    db.commit()
    body = client.get(f"/api/jobs/{job['id']}/candidates", headers=employer[1]).json()
    assert body["candidates"] == [] and body["hidden"] == 1
