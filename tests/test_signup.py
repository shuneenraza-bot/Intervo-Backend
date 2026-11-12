from sqlalchemy import select

from app.models import CandidateProfile, User
from tests.conftest import PASSWORD, candidate_payload, employer_payload, face_template


def test_signup_candidate(client, db):
    res = client.post("/api/auth/signup", json=candidate_payload(email="  Ayesha@Example.com "))
    assert res.status_code == 201
    body = res.json()
    assert body["token"]
    user = body["user"]
    assert user["role"] == "candidate"
    assert user["email"] == "ayesha@example.com"  # trimmed and lower-cased
    assert user["id"].startswith("cand-")
    assert user["face"] is None
    assert user["lastLogin"]["method"] == "signup"
    assert isinstance(user["createdAt"], int)
    assert "password" not in user and "passwordHash" not in user

    stored = db.scalars(select(User).where(User.email == "ayesha@example.com")).one()
    assert stored.password_hash.startswith("$argon2")
    assert PASSWORD not in stored.password_hash
    profile = db.get(CandidateProfile, stored.id)
    assert profile.skills == []
    assert profile.share_with_employers is False
    assert profile.consent_at is not None


def test_signup_candidate_with_face(client):
    res = client.post("/api/auth/signup", json=candidate_payload(face={"template": face_template()}))
    assert res.status_code == 201
    face = res.json()["user"]["face"]
    assert face["template"]["v"] == 2
    assert len(face["template"]["features"]) == 276
    assert isinstance(face["enrolledAt"], int)


def test_signup_employer(client, db):
    res = client.post("/api/auth/signup", json=employer_payload())
    assert res.status_code == 201
    user = res.json()["user"]
    assert user["role"] == "employer"
    assert user["company"] == "Northstar Digital"
    assert user["id"].startswith("emp-")
    assert db.get(CandidateProfile, user["id"]) is None  # profiles are for candidates only


def test_signup_employer_requires_company(client):
    for company in (None, "", " "):
        res = client.post("/api/auth/signup", json=employer_payload(company=company))
        assert res.status_code == 422
        assert res.json()["detail"] == "Enter your company name."


def test_signup_candidate_requires_consent(client):
    res = client.post("/api/auth/signup", json=candidate_payload(dataConsent=False))
    assert res.status_code == 422


def test_signup_admin_not_allowed(client, db):
    res = client.post("/api/auth/signup", json=candidate_payload(role="admin"))
    assert res.status_code == 422
    assert db.scalars(select(User)).first() is None


def test_signup_duplicate_email(client, candidate):
    res = client.post("/api/auth/signup", json=employer_payload(email="AYESHA@example.com"))
    assert res.status_code == 409
    assert res.json()["detail"] == "An account with this email already exists."


def test_signup_rejects_short_password_and_bad_email(client):
    assert client.post("/api/auth/signup", json=candidate_payload(password="short")).status_code == 422
    assert client.post("/api/auth/signup", json=candidate_payload(email="not-an-email")).status_code == 422


def test_signup_token_works_for_me(client, candidate):
    res = client.get("/api/auth/me", headers={"Authorization": f"Bearer {candidate['token']}"})
    assert res.status_code == 200
    assert res.json()["id"] == candidate["user"]["id"]
