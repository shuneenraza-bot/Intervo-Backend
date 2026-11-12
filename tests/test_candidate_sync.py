"""Candidate sync: PUT /api/profile and POST /api/sessions feed the employer's ranking."""

from datetime import datetime, timedelta, timezone

from app.models import CandidateProfile, InterviewSession
from tests.conftest import candidate_payload
from tests.test_employer import (  # noqa: F401  (catalog is an autouse fixture for this module too)
    AYESHA_SESSIONS,
    AYESHA_SKILLS,
    SECRET_ANSWER,
    catalog,
    create_job,
    employer,
    signup,
)

PROFILE = {
    "skills": AYESHA_SKILLS,
    "cv": {
        "education": [{"degree": "BS Computer Science", "institution": "UOG"}],
        "experienceYears": 1.5,
        "projects": [{"name": "Portfolio"}, {"name": "Shop"}],
    },
    "shareWithEmployers": True,
}


def session_body(days_ago: int, scores, **overrides) -> dict:
    date = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return {
        "id": f"s-local-{days_ago}", "roleId": "frontend", "mode": "video", "date": int(date.timestamp() * 1000),
        "score": round(sum(s for _, s in scores) / len(scores)),
        "answers": [
            {"questionId": "q-local-only", "question": f"About {skill}?", "skill": skill, "type": "technical",
             "score": score, "criteria": {"relevance": score}, "indicators": {"eyeContact": 80}, "reason": "role"}
            for skill, score in scores
        ],
        **overrides,
    }


# ---------- PUT /profile ----------

def test_candidate_saves_profile(client, db):
    user, headers = signup(client, candidate_payload())
    res = client.put("/api/profile", json=PROFILE, headers=headers)
    assert res.status_code == 200, res.text
    assert res.json() == PROFILE

    profile = db.get(CandidateProfile, user["id"])
    assert profile.skills == AYESHA_SKILLS
    assert profile.cv == PROFILE["cv"]
    assert profile.share_with_employers is True

    # a second PUT replaces everything, and cv: null clears the CV
    res = client.put("/api/profile", json={"skills": [" React ", "React", ""], "cv": None, "shareWithEmployers": False}, headers=headers)
    assert res.status_code == 200, res.text
    assert res.json() == {"skills": ["React"], "cv": None, "shareWithEmployers": False}
    db.expire_all()
    profile = db.get(CandidateProfile, user["id"])
    assert profile.skills == ["React"] and profile.cv is None and profile.share_with_employers is False


def test_profile_ignores_private_cv_fields(client, db):
    """Extra CV fields (contact details, raw text) are dropped, never stored."""
    user, headers = signup(client, candidate_payload())
    body = {**PROFILE, "cv": {**PROFILE["cv"], "contact": {"phone": "0300-1234567"}, "text": "raw cv text"}}
    assert client.put("/api/profile", json=body, headers=headers).status_code == 200
    assert db.get(CandidateProfile, user["id"]).cv == PROFILE["cv"]


def test_profile_roles_and_validation(client, employer):
    _, headers = signup(client, candidate_payload())
    assert client.put("/api/profile", json=PROFILE).status_code == 401
    assert client.put("/api/profile", json=PROFILE, headers=employer[1]).status_code == 403
    assert client.put("/api/profile", json={"skills": AYESHA_SKILLS}, headers=headers).status_code == 422  # no sharing flag
    bad_years = {**PROFILE, "cv": {**PROFILE["cv"], "experienceYears": -1}}
    assert client.put("/api/profile", json=bad_years, headers=headers).status_code == 422
    assert client.put("/api/profile", json={**PROFILE, "skills": ["x" * 121]}, headers=headers).status_code == 422


# ---------- POST /sessions ----------

def test_candidate_saves_session(client, db):
    user, headers = signup(client, candidate_payload())
    body = session_body(1, [("React", 82), ("Juggling", 40)])
    body["answers"][0]["answer"] = SECRET_ANSWER  # sent by mistake: must not be stored

    res = client.post("/api/sessions", json=body, headers=headers)
    assert res.status_code == 201, res.text
    saved = res.json()
    assert saved["id"] == "s-local-1" and saved["userId"] == user["id"]
    assert saved["roleId"] == "frontend" and saved["roleTitle"] == "Frontend Developer"
    assert saved["mode"] == "video" and saved["score"] == 61 and saved["date"] == body["date"]
    first, second = saved["answers"]
    assert first == {"questionId": None, "question": "About React?", "skill": "React", "type": "technical", "score": 82,
                     "criteria": {"relevance": 82}, "answer": "", "reason": "role", "followUp": None,
                     "indicators": {"eyeContact": 80}}
    assert second["skill"] == ""  # not in the server's skill library
    assert SECRET_ANSWER not in res.text

    stored = db.get(InterviewSession, "s-local-1")
    assert stored.candidate_id == user["id"]
    assert [a.answer for a in stored.answers] == ["", ""]


def test_session_resend_is_idempotent(client, db):
    _, headers = signup(client, candidate_payload())
    body = session_body(1, [("React", 82)])
    assert client.post("/api/sessions", json=body, headers=headers).status_code == 201
    again = client.post("/api/sessions", json={**body, "score": 5}, headers=headers)
    assert again.status_code == 200
    assert again.json()["score"] == 82  # the stored session, unchanged
    assert len(db.query(InterviewSession).all()) == 1

    # another candidate can't take or overwrite that id
    _, other = signup(client, candidate_payload(email="bilal@example.com", name="Bilal Ahmed"))
    assert client.post("/api/sessions", json=body, headers=other).status_code == 409

    # without an id the server makes one up; an unknown role is stored as no role
    res = client.post("/api/sessions", json=session_body(2, [("CSS", 60)], id=None, roleId="nope", date=None), headers=other)
    assert res.status_code == 201, res.text
    assert res.json()["id"].startswith("s-") and res.json()["roleId"] is None
    assert isinstance(res.json()["date"], int)


def test_session_roles_and_validation(client, employer):
    _, headers = signup(client, candidate_payload())
    body = session_body(1, [("React", 82)])
    assert client.post("/api/sessions", json=body).status_code == 401
    assert client.post("/api/sessions", json=body, headers=employer[1]).status_code == 403
    assert client.post("/api/sessions", json={**body, "score": 101}, headers=headers).status_code == 422
    assert client.post("/api/sessions", json={**body, "mode": "hologram"}, headers=headers).status_code == 422
    assert client.post("/api/sessions", json={**body, "answers": []}, headers=headers).status_code == 422
    assert client.post("/api/sessions", json={**body, "id": "bad id!"}, headers=headers).status_code == 422
    bad_answer = {**body["answers"][0], "type": "trivia"}
    assert client.post("/api/sessions", json={**body, "answers": [bad_answer]}, headers=headers).status_code == 422
    huge = {**body["answers"][0], "indicators": {"blob": "x" * 5000}}
    assert client.post("/api/sessions", json={**body, "answers": [huge]}, headers=headers).status_code == 422


# ---------- the point of it all ----------

def test_synced_candidate_gets_a_real_suitability_score(client, employer):
    """A fresh candidate scores 0%; after syncing profile and sessions the employer sees the
    same numbers as test_employer's hand-built Ayesha."""
    job = create_job(client, employer[1])
    user, headers = signup(client, candidate_payload())
    assert client.post(f"/api/jobs/{job['id']}/apply", json={"consent": True}, headers=headers).status_code == 201

    url = f"/api/jobs/{job['id']}/candidates"
    before = client.get(url, headers=employer[1]).json()["candidates"][0]
    assert before["fit"]["total"] == 0 and before["sessions"] == [] and before["cvSummary"] is None

    assert client.put("/api/profile", json=PROFILE, headers=headers).status_code == 200
    for days, scores in AYESHA_SESSIONS:
        assert client.post("/api/sessions", json=session_body(days, scores), headers=headers).status_code == 201

    res = client.get(url, headers=employer[1])
    entry = res.json()["candidates"][0]
    assert {f["key"]: f["value"] for f in entry["fit"]["factors"]} == {"cv": 90, "interview": 69, "consistency": 84}
    assert entry["fit"]["total"] == 80
    assert entry["fit"]["weak"] == ["Testing"]
    assert entry["cvSummary"] == {"topDegree": "BS Computer Science", "experienceYears": 1.5, "projectCount": 2}
    assert len(entry["sessions"]) == 3
    assert "eyeContact" not in res.text  # video indicators stay private

    # turning sharing off through the profile hides the candidate again
    assert client.put("/api/profile", json={**PROFILE, "shareWithEmployers": False}, headers=headers).status_code == 200
    body = client.get(url, headers=employer[1]).json()
    assert body["candidates"] == [] and body["hidden"] == 1
