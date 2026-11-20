"""Admin configuration endpoints (/api/admin/*) and the rule that changes apply immediately."""

import pytest

from app.config import settings
from app.db import new_id
from app.models import CandidateProfile, EvaluationCriterion, ScoringRules, User
from app.services.security import hash_password
from tests.conftest import PASSWORD, bearer, candidate_payload, employer_payload, face_template, finish_signin, sign_in, signup_full


@pytest.fixture(autouse=True)
def rules_only(monkeypatch):
    monkeypatch.setattr(settings, "ai_provider", "rules")  # no network in tests


@pytest.fixture
def admin(client, db):
    """Returns auth headers for an admin account (admins can't sign up; they're seeded)."""
    db.add(User(id=new_id("adm"), role="admin", name="Intervo Admin", email="admin@example.com",
                password_hash=hash_password(PASSWORD)))
    db.commit()
    return bearer(sign_in(client, "admin@example.com", "admin")["token"])


def signup(client, payload):
    body = signup_full(client, payload)
    return body["user"], bearer(body["token"])


def post(client, admin, path, body, status=201):
    res = client.post(f"/api/admin{path}", json=body, headers=admin)
    assert res.status_code == status, res.text
    return res.json()


@pytest.fixture
def lib(client, admin):
    """A small library built through the admin API itself."""
    domain = post(client, admin, "/domains", {"name": "Technology"})
    skills = {}
    for name, related in [("React", []), ("JavaScript", []), ("CSS", []), ("Communication", [])]:
        skills[name] = post(client, admin, "/skills", {"name": name, "aliases": [name.lower()], "related": related, "tip": f"Practise {name}."})
    role = post(client, admin, "/roles", {"title": "Frontend Developer", "domainId": domain["id"],
                                          "skills": [{"name": "React", "weight": 3}, {"name": "CSS", "weight": 2}]})
    return {"domain": domain, "skills": skills, "role": role}


# ---------- access ----------

ENDPOINTS = ["/domains", "/roles", "/skills", "/questions", "/criteria", "/rules", "/users", "/stats"]


@pytest.mark.parametrize("path", ENDPOINTS)
def test_admin_endpoints_need_an_admin(client, candidate, path):
    assert client.get(f"/api/admin{path}").status_code == 401
    as_candidate = {"Authorization": f"Bearer {candidate['token']}"}
    assert client.get(f"/api/admin{path}", headers=as_candidate).status_code == 403
    _, employer_headers = signup(client, employer_payload())
    assert client.get(f"/api/admin{path}", headers=employer_headers).status_code == 403


def test_writes_are_admin_only_too(client, candidate):
    headers = {"Authorization": f"Bearer {candidate['token']}"}
    assert client.post("/api/admin/domains", json={"name": "Sneaky"}, headers=headers).status_code == 403
    assert client.put("/api/admin/rules", json={"defaultQuestions": 6}, headers=headers).status_code == 403
    assert client.delete("/api/admin/skills/react", headers=headers).status_code == 403


# ---------- domains ----------

def test_domain_crud_duplicates_and_unknown_ids(client, admin):
    domain = post(client, admin, "/domains", {"name": "  Healthcare "})
    assert domain["name"] == "Healthcare" and domain["id"].startswith("dom-")
    assert post(client, admin, "/domains", {"name": "healthcare"}, 409)["detail"] == 'A domain named "healthcare" already exists.'
    assert client.post("/api/admin/domains", json={"name": "   "}, headers=admin).status_code == 422

    res = client.put(f"/api/admin/domains/{domain['id']}", json={"name": "Health"}, headers=admin)
    assert res.status_code == 200 and res.json()["name"] == "Health"
    other = post(client, admin, "/domains", {"name": "Finance"})
    assert client.put(f"/api/admin/domains/{other['id']}", json={"name": "health"}, headers=admin).status_code == 409
    assert client.put("/api/admin/domains/nope", json={"name": "X"}, headers=admin).status_code == 404

    assert [d["name"] for d in client.get("/api/admin/domains", headers=admin).json()] == ["Finance", "Health"]
    assert client.delete(f"/api/admin/domains/{domain['id']}", headers=admin).status_code == 204
    assert client.delete(f"/api/admin/domains/{domain['id']}", headers=admin).status_code == 404


def test_domain_used_by_a_role_cannot_be_deleted(client, admin, lib):
    res = client.delete(f"/api/admin/domains/{lib['domain']['id']}", headers=admin)
    assert res.status_code == 409
    assert "used by a role" in res.json()["detail"] and "Frontend Developer" in res.json()["detail"]
    assert len(client.get("/api/admin/domains", headers=admin).json()) == 1  # still there


# ---------- skills ----------

def test_skill_crud_and_validation(client, admin, lib):
    skill = post(client, admin, "/skills", {"name": "Git", "aliases": [" GitHub ", "github", "Version Control"], "related": ["React"], "tip": " Commit often. "})
    assert skill == {"id": "git", "name": "Git", "aliases": ["github", "version control"], "related": ["React"], "tip": "Commit often."}

    assert post(client, admin, "/skills", {"name": "git"}, 409)["detail"] == 'A skill named "git" already exists.'
    assert client.post("/api/admin/skills", json={"name": "X", "related": ["Juggling"]}, headers=admin).status_code == 422
    assert client.post("/api/admin/skills", json={"name": "Self", "related": ["Self"]}, headers=admin).status_code == 422
    assert client.post("/api/admin/skills", json={"name": ""}, headers=admin).status_code == 422

    res = client.put("/api/admin/skills/git", json={"name": "Git", "aliases": ["git"], "related": [], "tip": "New tip"}, headers=admin)
    assert res.status_code == 200 and res.json()["tip"] == "New tip" and res.json()["related"] == []
    assert client.put("/api/admin/skills/git", json={"name": "react"}, headers=admin).status_code == 409
    assert client.put("/api/admin/skills/nope", json={"name": "Nope"}, headers=admin).status_code == 404

    assert client.delete("/api/admin/skills/git", headers=admin).status_code == 204
    assert client.delete("/api/admin/skills/git", headers=admin).status_code == 404


def test_renaming_a_skill_updates_related_lists(client, admin, lib):
    post(client, admin, "/skills", {"name": "TypeScript", "related": ["JavaScript"]})
    res = client.put("/api/admin/skills/javascript", json={"name": "JS"}, headers=admin)
    assert res.status_code == 200
    by_name = {s["name"]: s for s in client.get("/api/admin/skills", headers=admin).json()}
    assert by_name["TypeScript"]["related"] == ["JS"]


def test_skill_used_by_a_role_or_job_cannot_be_deleted(client, admin, lib):
    res = client.delete("/api/admin/skills/react", headers=admin)
    assert res.status_code == 409
    assert res.json()["detail"].startswith("Skill is used by a role")

    # free it from the role: now only a job holds it
    client.put(f"/api/admin/roles/{lib['role']['id']}", headers=admin,
               json={"title": "Frontend Developer", "domainId": lib["domain"]["id"], "skills": [{"name": "CSS", "weight": 2}]})
    _, employer_headers = signup(client, employer_payload())
    job = {"title": "Frontend Intern", "roleId": lib["role"]["id"], "mode": "Remote", "location": "Lahore",
           "skills": [{"name": "React", "weight": 3}], "success": {"minMatch": 50, "notes": ""}}
    assert client.post("/api/jobs", json=job, headers=employer_headers).status_code == 201
    res = client.delete("/api/admin/skills/react", headers=admin)
    assert res.status_code == 409 and res.json()["detail"].startswith("Skill is used by a job")

    # an unused skill goes, along with its questions and mentions in other skills' related lists
    post(client, admin, "/skills", {"name": "Git", "related": ["JavaScript"]})
    post(client, admin, "/questions", {"skill": "Git", "type": "technical", "text": "Explain what a rebase does."})
    client.put("/api/admin/skills/javascript", json={"name": "JavaScript", "related": ["Git"]}, headers=admin)
    assert client.delete("/api/admin/skills/git", headers=admin).status_code == 204
    by_name = {s["name"]: s for s in client.get("/api/admin/skills", headers=admin).json()}
    assert by_name["JavaScript"]["related"] == []
    assert client.get("/api/admin/questions", headers=admin).json() == []


# ---------- roles ----------

def test_role_crud_with_weights(client, admin, lib):
    body = {"title": "UI Engineer", "domainId": lib["domain"]["id"],
            "skills": [{"name": "CSS", "weight": 1}, {"name": "React", "weight": 3}]}
    role = post(client, admin, "/roles", body)
    assert role["id"].startswith("role-")
    assert role["skills"] == [{"name": "React", "weight": 3}, {"name": "CSS", "weight": 1}]  # heaviest first

    assert post(client, admin, "/roles", {**body, "title": "ui engineer"}, 409)["detail"].startswith("A job role titled")
    for bad in ({"skills": [{"name": "React", "weight": 4}]}, {"skills": [{"name": "React", "weight": 0}]},
                {"skills": []}, {"skills": [{"name": "Nope", "weight": 2}]},
                {"skills": [{"name": "React", "weight": 2}, {"name": "React", "weight": 3}]}, {"domainId": "nope"}, {"title": " "}):
        assert client.post("/api/admin/roles", json={**body, "title": "Other", **bad}, headers=admin).status_code == 422, bad

    res = client.put(f"/api/admin/roles/{role['id']}", json={**body, "skills": [{"name": "React", "weight": 2}]}, headers=admin)
    assert res.status_code == 200 and res.json()["skills"] == [{"name": "React", "weight": 2}]
    assert client.put("/api/admin/roles/nope", json=body, headers=admin).status_code == 404
    assert client.delete(f"/api/admin/roles/{role['id']}", headers=admin).status_code == 204
    assert client.delete(f"/api/admin/roles/{role['id']}", headers=admin).status_code == 404


def test_role_used_by_a_job_cannot_be_deleted(client, admin, lib):
    _, employer_headers = signup(client, employer_payload())
    job = {"title": "Frontend Intern", "roleId": lib["role"]["id"], "mode": "Remote", "location": "Lahore",
           "skills": [{"name": "React", "weight": 3}], "success": {"minMatch": 50, "notes": ""}}
    assert client.post("/api/jobs", json=job, headers=employer_headers).status_code == 201
    res = client.delete(f"/api/admin/roles/{lib['role']['id']}", headers=admin)
    assert res.status_code == 409 and "used by a job" in res.json()["detail"]


# ---------- question templates ----------

def test_question_crud(client, admin, lib):
    body = {"skill": "React", "type": "technical", "text": "  What is a component?  ", "keywords": [" State ", "props", "state"], "followUp": "Give an example."}
    q = post(client, admin, "/questions", body)
    assert q == {"id": q["id"], "skill": "React", "type": "technical", "text": "What is a component?",
                 "keywords": ["state", "props"], "followUp": "Give an example."}

    assert post(client, admin, "/questions", {**body, "text": "what is a component?"}, 409)["detail"] == "React already has this question."
    assert client.post("/api/admin/questions", json={**body, "text": "short"}, headers=admin).status_code == 422
    assert client.post("/api/admin/questions", json={**body, "type": "oral"}, headers=admin).status_code == 422
    assert client.post("/api/admin/questions", json={**body, "skill": "Juggling"}, headers=admin).status_code == 422

    res = client.put(f"/api/admin/questions/{q['id']}", json={**body, "skill": "CSS", "type": "behavioral", "text": "Describe a layout you built."}, headers=admin)
    assert res.status_code == 200 and (res.json()["skill"], res.json()["type"]) == ("CSS", "behavioral")
    assert client.put("/api/admin/questions/nope", json=body, headers=admin).status_code == 404

    assert [x["id"] for x in client.get("/api/admin/questions?skill=CSS", headers=admin).json()] == [q["id"]]
    assert client.get("/api/admin/questions?skill=React", headers=admin).json() == []
    assert client.delete(f"/api/admin/questions/{q['id']}", headers=admin).status_code == 204
    assert client.delete(f"/api/admin/questions/{q['id']}", headers=admin).status_code == 404


# ---------- criteria and rules ----------

def test_criteria_update_and_validation(client, admin, db):
    db.add_all([EvaluationCriterion(key="relevance", label="Relevance", weight=2, applies_to="all", enabled=True),
                EvaluationCriterion(key="clarity", label="Clarity", weight=1, applies_to="all", enabled=True)])
    db.commit()
    assert {c["key"] for c in client.get("/api/admin/criteria", headers=admin).json()} == {"relevance", "clarity"}

    res = client.put("/api/admin/criteria", headers=admin, json={"criteria": [{"key": "clarity", "weight": 3, "enabled": False}]})
    assert res.status_code == 200
    assert {c["key"]: (c["weight"], c["enabled"]) for c in res.json()} == {"relevance": (2, True), "clarity": (3, False)}

    def put(criteria):
        return client.put("/api/admin/criteria", headers=admin, json={"criteria": criteria})
    assert put([{"key": "clarity", "weight": 4, "enabled": True}]).status_code == 422
    assert put([{"key": "clarity", "weight": 0, "enabled": True}]).status_code == 422
    assert put([{"key": "nope", "weight": 2, "enabled": True}]).status_code == 404
    assert put([{"key": "clarity", "weight": 1, "enabled": True}, {"key": "clarity", "weight": 2, "enabled": True}]).status_code == 422
    assert put([{"key": "relevance", "weight": 2, "enabled": False}]).status_code == 422  # would leave none enabled
    db.expire_all()
    assert db.get(EvaluationCriterion, "relevance").enabled is True  # the rejected change wasn't saved


def test_rules_defaults_partial_update_and_ranges(client, admin, db):
    db.get(ScoringRules, 1).data = {"faceThreshold": 0.6, "suitability": {"cv": 40, "interview": 45, "consistency": 15}}
    db.commit()
    assert client.get("/api/admin/rules", headers=admin).json() == {
        "weakThreshold": 60, "weakMinSessions": 2, "followUpBelow": 55, "defaultQuestions": 5, "faceThreshold": 0.6}

    res = client.put("/api/admin/rules", json={"defaultQuestions": 4, "weakThreshold": 70}, headers=admin)
    assert res.status_code == 200
    assert res.json() == {"weakThreshold": 70, "weakMinSessions": 2, "followUpBelow": 55, "defaultQuestions": 4, "faceThreshold": 0.6}
    db.expire_all()
    assert "suitability" not in db.get(ScoringRules, 1).data  # the old weights are gone for good

    for bad in ({"weakThreshold": 29}, {"weakThreshold": 91}, {"weakMinSessions": 0}, {"weakMinSessions": 6},
                {"followUpBelow": 29}, {"followUpBelow": 81}, {"defaultQuestions": 2}, {"defaultQuestions": 7},
                {"faceThreshold": 0.29}, {"faceThreshold": 0.91}):
        assert client.put("/api/admin/rules", json=bad, headers=admin).status_code == 422, bad
    assert client.get("/api/admin/rules", headers=admin).json()["defaultQuestions"] == 4


# ---------- users and stats ----------

def test_users_list_has_no_secrets_and_stats_count(client, admin, db):
    ayesha, _ = signup(client, candidate_payload())
    signup(client, employer_payload())
    users = client.get("/api/admin/users", headers=admin)
    assert users.status_code == 200
    rows = {u["email"]: u for u in users.json()}
    assert rows["ayesha@example.com"]["faceEnrolled"] is True and rows["hr@example.com"]["faceEnrolled"] is True
    assert rows["admin@example.com"]["faceEnrolled"] is True  # the admin fixture signed in, so enrolled too
    assert rows["hr@example.com"]["company"] == "Northstar Digital"
    assert {u["role"] for u in users.json()} == {"candidate", "employer", "admin"}
    for forbidden in ("password", "hash", "template", "features", "argon"):
        assert forbidden not in users.text.lower()
    assert [u["role"] for u in client.get("/api/admin/users?role=employer", headers=admin).json()] == ["employer"]

    assert client.get("/api/admin/stats", headers=admin).json() == {
        "candidates": 1, "employers": 1, "admins": 1, "sessions": 0, "jobs": 0, "openJobs": 0, "applications": 0,
        "domains": 0, "roles": 0, "skills": 0, "questions": 0, "criteriaEnabled": 0}


# ---------- changes apply immediately ----------

def test_config_changes_apply_to_the_next_request(client, admin, lib, db):
    """Nothing is cached: every admin change shows up in /config and in the engines right away."""
    config = lambda: client.get("/api/config", headers=admin).json()  # noqa: E731

    # /config
    post(client, admin, "/skills", {"name": "Git"})
    assert "Git" in [s["name"] for s in config()["skills"]]
    client.put("/api/admin/rules", json={"defaultQuestions": 3}, headers=admin)
    assert config()["rules"]["defaultQuestions"] == 3

    # the interview engine: question count follows the rule, and a new template is used
    client.put(f"/api/admin/roles/{lib['role']['id']}", headers=admin, json={
        "title": "Frontend Developer", "domainId": lib["domain"]["id"],
        "skills": [{"name": "React", "weight": 3}, {"name": "CSS", "weight": 2}, {"name": "JavaScript", "weight": 2}]})
    for skill in ("React", "CSS", "JavaScript"):
        post(client, admin, "/questions", {"skill": skill, "type": "technical", "text": f"Explain {skill} to a beginner."})
    post(client, admin, "/questions", {"skill": "Communication", "type": "behavioral", "text": "Tell me about a disagreement."})
    candidate_headers = signup(client, candidate_payload())[1]

    def start():
        res = client.post("/api/interviews", json={"roleId": lib["role"]["id"], "mode": "text"}, headers=candidate_headers)
        assert res.status_code == 201, res.text
        return res.json()

    assert len(start()["questions"]) == 3
    client.put("/api/admin/rules", json={"defaultQuestions": 4}, headers=admin)
    assert len(start()["questions"]) == 4

    # the employer's CV match: a related skill added by the admin gives partial credit at once
    employer_headers = signup(client, employer_payload())[1]
    job = {"title": "Frontend Intern", "roleId": lib["role"]["id"], "mode": "Remote", "location": "Lahore",
           "skills": [{"name": "React", "weight": 2}], "success": {"minMatch": 0, "notes": ""}}
    job_id = client.post("/api/jobs", json=job, headers=employer_headers).json()["id"]
    applicant, applicant_headers = signup(client, candidate_payload(email="bilal@example.com", name="Bilal"))
    profile = db.get(CandidateProfile, applicant["id"]) or CandidateProfile(user_id=applicant["id"])
    profile.skills = ["JavaScript"]
    profile.parsed_cv = {"skills": ["JavaScript"]}
    db.add(profile)
    db.commit()
    client.post(f"/api/jobs/{job_id}/apply", json={"consent": True}, headers=applicant_headers)

    def percentage():
        body = client.get(f"/api/jobs/{job_id}/candidates", headers=employer_headers).json()
        return body["candidates"][0]["match"]["percentage"]

    assert percentage() == 0
    client.put("/api/admin/skills/react", json={"name": "React", "related": ["JavaScript"]}, headers=admin)
    assert percentage() == 50  # half credit for the related skill
    client.put("/api/admin/skills/react", json={"name": "React", "related": []}, headers=admin)
    assert percentage() == 0


# ---------- reset face ----------

def test_reset_face_forces_re_enrolment(client, admin):
    ayesha, ayesha_headers = signup(client, candidate_payload())
    assert client.get("/api/auth/me", headers=ayesha_headers).status_code == 200

    res = client.post(f"/api/admin/users/{ayesha['id']}/reset-face", headers=admin)
    assert res.status_code == 200
    row = res.json()
    assert row["id"] == ayesha["id"] and row["faceEnrolled"] is False
    assert "face" not in row and "template" not in row

    # The open session stops working until the user enrols again.
    assert client.get("/api/auth/me", headers=ayesha_headers).status_code == 401
    listed = {u["email"]: u for u in client.get("/api/admin/users", headers=admin).json()}
    assert listed["ayesha@example.com"]["faceEnrolled"] is False

    # Next sign-in: password, then the face step asks to enrol (not verify) a new face.
    step = client.post("/api/auth/login", json={"email": "ayesha@example.com", "role": "candidate", "password": PASSWORD}).json()
    assert step["faceEnrolled"] is False
    again = finish_signin(client, step, offset=0.3)
    assert client.get("/api/auth/me", headers=bearer(again["token"])).status_code == 200
    # The new face is the one that now verifies.
    step = client.post("/api/auth/login", json={"email": "ayesha@example.com", "role": "candidate", "password": PASSWORD}).json()
    assert step["faceEnrolled"] is True
    assert finish_signin(client, step, offset=0.3)["token"]


def test_reset_face_is_admin_only_and_needs_a_real_user(client, admin, candidate):
    url = f"/api/admin/users/{candidate['user']['id']}/reset-face"
    assert client.post(url, headers=bearer(candidate["token"])).status_code == 403
    assert client.post(url).status_code == 401
    assert client.post("/api/admin/users/nobody/reset-face", headers=admin).status_code == 404
    # A candidate can't reset their own face either; it stays enrolled.
    assert client.get("/api/auth/me", headers=bearer(candidate["token"])).status_code == 200
