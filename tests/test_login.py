from datetime import datetime, timedelta, timezone

from fastapi import Depends

from app.deps import require_role
from app.main import app
from app.models import User
from tests.conftest import PASSWORD, employer_payload, face_template

EMAIL = "ayesha@example.com"


def login(client, **fields):
    return client.post("/api/auth/login", json={"email": EMAIL, "role": "candidate", **fields})


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------- password ----------

def test_login_with_password(client, candidate):
    res = login(client, password=PASSWORD)
    assert res.status_code == 200
    body = res.json()
    assert body["user"]["id"] == candidate["user"]["id"]
    assert body["user"]["lastLogin"]["method"] == "password"
    assert client.get("/api/auth/me", headers=auth(body["token"])).status_code == 200


def test_login_wrong_password(client, candidate):
    res = login(client, password="Wrong@1234")
    assert res.status_code == 401
    assert res.json()["detail"] == "Incorrect password."


def test_login_unknown_email(client):
    res = login(client, password=PASSWORD)
    assert res.status_code == 404
    assert res.json()["detail"] == "No account found with this email."


def test_login_wrong_role_does_not_reveal_real_role(client, candidate):
    res = client.post("/api/auth/login", json={"email": EMAIL, "role": "employer", "password": PASSWORD})
    assert res.status_code == 404
    assert res.json()["detail"] == "No employer account found with this email."


def test_login_needs_exactly_one_method(client, face_candidate):
    assert login(client).status_code == 422
    assert login(client, password=PASSWORD, faceTemplate=face_template()).status_code == 422


# ---------- lockout ----------

def test_lockout_after_five_wrong_passwords(client, candidate, db):
    for _ in range(4):
        assert login(client, password="Wrong@1234").status_code == 401

    fifth = login(client, password="Wrong@1234")
    assert fifth.status_code == 429
    assert fifth.headers["Retry-After"] == "60"

    # While locked, even the correct password is rejected.
    locked = login(client, password=PASSWORD)
    assert locked.status_code == 429
    assert 0 < int(locked.headers["Retry-After"]) <= 60

    # Once the 60 seconds have passed, sign-in works again.
    user = db.get(User, candidate["user"]["id"])
    user.locked_until = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()
    assert login(client, password=PASSWORD).status_code == 200


def test_lockout_also_blocks_face_login(client, face_candidate):
    for _ in range(5):
        login(client, password="Wrong@1234")
    assert login(client, faceTemplate=face_template()).status_code == 429


def test_successful_login_resets_failed_attempts(client, candidate):
    for _ in range(4):
        assert login(client, password="Wrong@1234").status_code == 401
    assert login(client, password=PASSWORD).status_code == 200
    # The counter started again, so four more wrong attempts still don't lock the account.
    for _ in range(4):
        assert login(client, password="Wrong@1234").status_code == 401
    assert login(client, password=PASSWORD).status_code == 200


# ---------- face ----------

def test_login_with_face(client, face_candidate):
    res = login(client, faceTemplate=face_template(offset=0.01))  # close to the enrolled face
    assert res.status_code == 200
    assert res.json()["user"]["lastLogin"]["method"] == "face"
    assert res.json()["token"]


def test_login_face_mismatch(client, face_candidate):
    res = login(client, faceTemplate=face_template(offset=0.2))  # a different face
    assert res.status_code == 401
    assert res.json()["detail"] == "Face didn't match this account."


def test_login_face_uses_threshold_from_scoring_rules(client, face_candidate, db):
    from app.models import ScoringRules

    template = face_template(offset=0.03)  # similarity 0.75
    assert login(client, faceTemplate=template).status_code == 200
    db.get(ScoringRules, 1).data = {"faceThreshold": 0.9}
    db.commit()
    assert login(client, faceTemplate=template).status_code == 401


def test_login_face_not_enrolled(client, candidate):
    res = login(client, faceTemplate=face_template())
    assert res.status_code == 400
    assert res.json()["detail"] == "Face ID isn't set up for this account."


def test_face_locked_after_three_failures_until_password_login(client, face_candidate):
    for _ in range(3):
        assert login(client, faceTemplate=face_template(offset=0.2)).status_code == 401
    # Even the right face is refused now.
    locked = login(client, faceTemplate=face_template())
    assert locked.status_code == 401
    assert "locked" in locked.json()["detail"]
    # A password sign-in unlocks Face ID.
    assert login(client, password=PASSWORD).status_code == 200
    assert login(client, faceTemplate=face_template()).status_code == 200


# ---------- lookup, me, face enrolment, roles ----------

def test_lookup(client, candidate):
    res = client.post("/api/auth/lookup", json={"email": EMAIL, "role": "candidate"})
    assert res.status_code == 200
    assert res.json() == {"faceEnabled": False}
    assert client.post("/api/auth/lookup", json={"email": EMAIL, "role": "admin"}).status_code == 404


def test_me_requires_valid_token(client):
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/auth/me", headers=auth("not-a-token")).status_code == 401


def test_enrol_replace_and_delete_face(client, candidate):
    headers = auth(candidate["token"])

    res = client.put("/api/auth/face", json={"template": face_template()}, headers=headers)
    assert res.status_code == 200
    assert res.json()["face"]["template"]["v"] == 2
    assert client.post("/api/auth/lookup", json={"email": EMAIL, "role": "candidate"}).json() == {"faceEnabled": True}
    assert login(client, faceTemplate=face_template()).status_code == 200

    # Replace with a different face: the old one stops working.
    assert client.put("/api/auth/face", json={"template": face_template(offset=0.3)}, headers=headers).status_code == 200
    assert login(client, faceTemplate=face_template()).status_code == 401
    assert login(client, faceTemplate=face_template(offset=0.3)).status_code == 200

    res = client.delete("/api/auth/face", headers=headers)
    assert res.status_code == 200
    assert res.json()["face"] is None
    assert login(client, faceTemplate=face_template(offset=0.3)).status_code == 400

    assert client.put("/api/auth/face", json={"template": face_template()}).status_code == 401  # no token


def test_require_role(client, candidate):
    @app.get("/api/_test/employers-only")
    def employers_only(user: User = Depends(require_role("employer"))):
        return {"id": user.id}

    employer = client.post("/api/auth/signup", json=employer_payload()).json()
    assert client.get("/api/_test/employers-only", headers=auth(employer["token"])).status_code == 200
    assert client.get("/api/_test/employers-only", headers=auth(candidate["token"])).status_code == 403
    assert client.get("/api/_test/employers-only").status_code == 401


def test_health(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"
