from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends

from app.config import settings
from app.deps import require_role
from app.main import app
from app.models import ScoringRules, User
from app.services.security import ALGORITHM
from tests.conftest import (
    PASSWORD, bearer, candidate_payload, employer_payload, face_template, finish_signin, sign_in, signup_full,
)

EMAIL = "ayesha@example.com"
BLINK = {"blink": True}


def password_step(client, **fields):
    return client.post("/api/auth/login", json={"email": EMAIL, "role": "candidate", "password": PASSWORD, **fields})


def verify(client, pending_token, offset=0.0, liveness=BLINK):
    return client.post("/api/auth/face/verify", headers=bearer(pending_token),
                       json={"template": face_template(offset), "liveness": liveness})


def pending(client) -> str:
    res = password_step(client)
    assert res.status_code == 200, res.text
    return res.json()["pendingToken"]


# ---------- password step: never a full token ----------

def test_password_alone_gives_no_access(client, candidate):
    res = password_step(client)
    assert res.status_code == 200
    body = res.json()
    assert body["faceEnrolled"] is True and body["expiresIn"] == 300
    assert "token" not in body and "user" not in body
    claims = jwt.decode(body["pendingToken"], settings.jwt_secret, algorithms=[ALGORITHM])
    assert claims["scope"] == "face_pending"
    assert claims["exp"] - claims["iat"] == 300
    assert client.get("/api/auth/me", headers=bearer(body["pendingToken"])).status_code == 401


def test_login_takes_only_a_password(client, candidate):
    assert client.post("/api/auth/login", json={"email": EMAIL, "role": "candidate"}).status_code == 422
    # Face-only login is gone: a face template in the body is not a way in.
    res = client.post("/api/auth/login", json={"email": EMAIL, "role": "candidate", "faceTemplate": face_template()})
    assert res.status_code == 422
    assert client.post("/api/auth/lookup", json={"email": EMAIL, "role": "candidate"}).status_code == 404


def test_login_wrong_password(client, candidate):
    res = password_step(client, password="Wrong@1234")
    assert res.status_code == 401
    assert res.json()["detail"] == "Incorrect password."


def test_login_unknown_email(client):
    res = password_step(client)
    assert res.status_code == 404
    assert res.json()["detail"] == "No account found with this email."


def test_login_wrong_role_does_not_reveal_real_role(client, candidate):
    res = client.post("/api/auth/login", json={"email": EMAIL, "role": "employer", "password": PASSWORD})
    assert res.status_code == 404
    assert res.json()["detail"] == "No employer account found with this email."


# ---------- face-pending token is rejected everywhere else ----------

def test_pending_token_is_rejected_on_every_normal_endpoint(client, candidate):
    headers = bearer(pending(client))
    for method, path in [
        ("get", "/api/auth/me"), ("put", "/api/auth/face"), ("post", "/api/cv"), ("get", "/api/jobs"),
        ("get", "/api/interviews"), ("get", "/api/admin/users"), ("get", "/api/progress"),
    ]:
        assert client.request(method, path, headers=headers).status_code == 401, path


def test_full_token_is_rejected_on_the_face_step(client, candidate):
    full = bearer(candidate["token"])
    body = {"template": face_template(), "liveness": BLINK}
    assert client.post("/api/auth/face/verify", json=body, headers=full).status_code == 401
    assert client.post("/api/auth/face/enroll", json={"template": face_template()}, headers=full).status_code == 401
    assert client.post("/api/auth/face/verify", json=body).status_code == 401


def test_expired_pending_token_is_rejected(client, candidate):
    now = datetime.now(timezone.utc)
    stale = jwt.encode({"sub": candidate["user"]["id"], "role": "candidate", "scope": "face_pending",
                        "iat": now - timedelta(minutes=6), "exp": now - timedelta(minutes=1)},
                       settings.jwt_secret, algorithm=ALGORITHM)
    assert verify(client, stale).status_code == 401


def test_token_without_a_scope_is_rejected(client, candidate):
    now = datetime.now(timezone.utc)
    legacy = jwt.encode({"sub": candidate["user"]["id"], "role": "candidate", "iat": now, "exp": now + timedelta(hours=1)},
                        settings.jwt_secret, algorithm=ALGORITHM)
    assert client.get("/api/auth/me", headers=bearer(legacy)).status_code == 401


# ---------- face step: enrol, then verify ----------

def test_enrol_then_verify_works(client):
    # First sign-in: no face yet, so the face step enrols and returns the full token.
    pending_first = client.post("/api/auth/signup", json=candidate_payload()).json()
    assert pending_first["faceEnrolled"] is False
    first = finish_signin(client, pending_first)
    assert client.get("/api/auth/me", headers=bearer(first["token"])).status_code == 200

    # Next sign-in: the face is enrolled, so the face step verifies it (a slightly different capture).
    again = password_step(client).json()
    assert again["faceEnrolled"] is True
    res = verify(client, again["pendingToken"], offset=0.01)
    assert res.status_code == 200
    assert res.json()["user"]["lastLogin"]["method"] == "face"
    assert client.get("/api/auth/me", headers=bearer(res.json()["token"])).json()["id"] == first["user"]["id"]


def test_enrolled_account_cannot_enrol_again_with_a_pending_token(client, candidate):
    res = client.post("/api/auth/face/enroll", headers=bearer(pending(client)), json={"template": face_template(0.3)})
    assert res.status_code == 409
    assert verify(client, pending(client)).status_code == 200  # the original face still works


def test_verify_before_enrolment_is_refused(client):
    token = client.post("/api/auth/signup", json=candidate_payload()).json()["pendingToken"]
    assert verify(client, token).status_code == 400


def test_wrong_face_is_rejected(client, candidate):
    res = verify(client, pending(client), offset=0.2)
    assert res.status_code == 401
    assert res.json()["detail"] == "Face didn't match this account. 2 attempts left."


def test_verify_needs_a_passed_blink(client, candidate):
    token = pending(client)
    assert verify(client, token, liveness={"blink": False}).status_code == 400
    assert client.post("/api/auth/face/verify", headers=bearer(token), json={"template": face_template()}).status_code == 422
    assert verify(client, token).status_code == 200  # a refused blink check doesn't burn an attempt


def test_verify_uses_threshold_from_scoring_rules(client, candidate, db):
    template = 0.03  # similarity 0.75
    assert verify(client, pending(client), offset=template).status_code == 200
    db.get(ScoringRules, 1).data = {"faceThreshold": 0.9}
    db.commit()
    assert verify(client, pending(client), offset=template).status_code == 401


# ---------- lockouts ----------

def test_three_wrong_faces_block_the_login_for_five_minutes(client, candidate, db):
    token = pending(client)
    assert verify(client, token, offset=0.2).status_code == 401
    assert verify(client, token, offset=0.2).status_code == 401
    third = verify(client, token, offset=0.2)
    assert third.status_code == 429
    assert third.headers["Retry-After"] == "300"

    # Blocked: even the right face, and a new password step, are refused.
    assert verify(client, token).status_code == 429
    blocked = password_step(client)
    assert blocked.status_code == 429
    assert 0 < int(blocked.headers["Retry-After"]) <= 300

    # After the 5 minutes the old pending token is still dead; a new password step is needed.
    user = db.get(User, candidate["user"]["id"])
    user.locked_until = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()
    assert verify(client, token).status_code == 401
    assert verify(client, pending(client)).status_code == 200


def test_lockout_after_five_wrong_passwords(client, candidate, db):
    for _ in range(4):
        assert password_step(client, password="Wrong@1234").status_code == 401

    fifth = password_step(client, password="Wrong@1234")
    assert fifth.status_code == 429
    assert fifth.headers["Retry-After"] == "60"

    # While locked, even the correct password is rejected.
    locked = password_step(client)
    assert locked.status_code == 429
    assert 0 < int(locked.headers["Retry-After"]) <= 60

    # Once the 60 seconds have passed, sign-in works again.
    user = db.get(User, candidate["user"]["id"])
    user.locked_until = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()
    assert password_step(client).status_code == 200


def test_successful_password_resets_failed_attempts(client, candidate):
    for _ in range(4):
        assert password_step(client, password="Wrong@1234").status_code == 401
    assert password_step(client).status_code == 200
    # The counter started again, so four more wrong attempts still don't lock the account.
    for _ in range(4):
        assert password_step(client, password="Wrong@1234").status_code == 401
    assert password_step(client).status_code == 200


# ---------- me, re-enrol, roles ----------

def test_me_requires_valid_token(client):
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/auth/me", headers=bearer("not-a-token")).status_code == 401


def test_re_enrol_replaces_the_face_and_there_is_no_delete(client, candidate):
    headers = bearer(candidate["token"])
    res = client.put("/api/auth/face", json={"template": face_template(offset=0.3)}, headers=headers)
    assert res.status_code == 200
    assert res.json()["face"]["template"]["v"] == 2

    # The old face stops working; the new one works.
    assert verify(client, pending(client)).status_code == 401
    assert verify(client, pending(client), offset=0.3).status_code == 200

    assert client.delete("/api/auth/face", headers=headers).status_code == 405
    assert client.put("/api/auth/face", json={"template": face_template()}).status_code == 401  # no token


def test_require_role(client, candidate):
    @app.get("/api/_test/employers-only")
    def employers_only(user: User = Depends(require_role("employer"))):
        return {"id": user.id}

    employer = signup_full(client, employer_payload())
    assert client.get("/api/_test/employers-only", headers=bearer(employer["token"])).status_code == 200
    assert client.get("/api/_test/employers-only", headers=bearer(candidate["token"])).status_code == 403
    assert client.get("/api/_test/employers-only").status_code == 401


def test_sign_in_helper_round_trip(client, candidate):
    again = sign_in(client, EMAIL)
    assert again["user"]["id"] == candidate["user"]["id"]


def test_health(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"
