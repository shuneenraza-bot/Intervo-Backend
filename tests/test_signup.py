from sqlalchemy import select

from app.models import CandidateProfile, User
from tests.conftest import (
    PASSWORD, bearer, candidate_payload, employer_payload, face_template, finish_signin, signup_full,
)


def test_signup_returns_only_a_face_pending_token(client, db):
    res = client.post("/api/auth/signup", json=candidate_payload(email="  Ayesha@Example.com "))
    assert res.status_code == 201
    body = res.json()
    assert body["pendingToken"] and body["faceEnrolled"] is False and body["expiresIn"] == 300
    assert "token" not in body and "user" not in body

    stored = db.scalars(select(User).where(User.email == "ayesha@example.com")).one()  # trimmed, lower-cased
    assert stored.id.startswith("cand-")
    assert stored.face_template is None
    assert stored.password_hash.startswith("$argon2")
    assert PASSWORD not in stored.password_hash
    profile = db.get(CandidateProfile, stored.id)
    assert profile.skills == [] and profile.share_with_employers is False and profile.consent_at is not None


def test_signup_ignores_a_face_in_the_body(client, db):
    res = client.post("/api/auth/signup", json={**candidate_payload(), "face": {"template": face_template()}})
    assert res.status_code == 201
    assert db.scalars(select(User)).one().face_template is None


def test_signup_is_not_complete_until_the_face_is_enrolled(client):
    pending = client.post("/api/auth/signup", json=candidate_payload()).json()
    # The pending token opens nothing else.
    assert client.get("/api/auth/me", headers=bearer(pending["pendingToken"])).status_code == 401

    body = finish_signin(client, pending)
    assert body["user"]["lastLogin"]["method"] == "signup"
    assert body["user"]["face"]["enrolled"] is True and "template" not in body["user"]["face"]
    assert isinstance(body["user"]["face"]["enrolledAt"], int)
    assert client.get("/api/auth/me", headers=bearer(body["token"])).json()["id"] == body["user"]["id"]


def test_signup_employer(client, db):
    user = signup_full(client, employer_payload())["user"]
    assert user["role"] == "employer"
    assert user["company"] == "Northstar Digital"
    assert user["id"].startswith("emp-")
    assert "password" not in user and "passwordHash" not in user
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
