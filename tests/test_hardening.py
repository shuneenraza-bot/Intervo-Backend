"""Hardening: encrypted face templates, server-checked blink, password rule, hidden candidate
names, one response per shortlist."""

import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.models import ApplicationStatusEvent, CandidateProfile, User
from app.services import face_crypto
from app.services.liveness import BlinkSample, blink_ok
from tests.conftest import (
    PASSWORD, TestingSession, bearer, blink_liveness, candidate_payload, engine, face_template, sign_in,
)
from tests.test_employer import (  # noqa: F401
    ayesha, catalog, create_job, employer, other_employer, signup,
)
from tests.test_shortlist import apply, respond, shortlist


# ---------- 1. face templates are encrypted at rest ----------

def raw_face(user_id: str):
    with engine.connect() as conn:
        return conn.execute(text("SELECT face_template FROM users WHERE id = :i"), {"i": user_id}).scalar()


def test_face_template_is_ciphertext_in_the_database(client, candidate, db):
    stored = raw_face(candidate["user"]["id"])
    assert stored["enc"] == 1 and "features" not in stored and "v" not in stored
    assert face_crypto.decrypt_template(stored)["features"] == face_template()["features"]
    user = db.get(User, candidate["user"]["id"])
    assert len(user.face_template["features"]) == 276  # code still sees the plain template


def test_a_legacy_plain_template_still_signs_in(client, candidate):
    with engine.begin() as conn:  # what an older version stored
        conn.execute(text("UPDATE users SET face_template = CAST(:t AS jsonb) WHERE id = :i"),
                     {"t": json.dumps(face_template()), "i": candidate["user"]["id"]})
    assert "features" in raw_face(candidate["user"]["id"])
    assert sign_in(client, "ayesha@example.com")["token"]


def test_the_template_is_never_sent_back(client, candidate):
    me = client.get("/api/auth/me", headers=bearer(candidate["token"]))
    assert me.json()["face"]["enrolled"] is True
    assert "features" not in me.text and "template" not in me.text


# ---------- 2. blink evidence is checked on the server ----------

def pend(client):
    res = client.post("/api/auth/login", json={"email": "ayesha@example.com", "role": "candidate", "password": PASSWORD})
    return res.json()["pendingToken"]


def verify_with(client, liveness):
    return client.post("/api/auth/face/verify", headers=bearer(pend(client)),
                       json={"template": face_template(), "liveness": liveness})


def test_blink_series_rules():
    def s(*pairs):
        return [BlinkSample(t=t, v=v) for t, v in pairs]

    good = s((0, .05), (100, .06), (200, .05), (300, .4), (400, .8), (500, .1))
    assert blink_ok(good)
    assert not blink_ok(s((0, .05), (100, .05), (200, .05), (300, .05), (400, .05)))  # never closed
    assert not blink_ok(s((0, .8), (100, .8), (200, .8), (300, .8), (400, .8)))  # never open first
    assert not blink_ok(good[:4])  # too few frames
    assert not blink_ok(s((0, .05), (100, .05), (100, .8), (200, .8), (300, .8)))  # time not increasing
    assert not blink_ok(s((0, .05), (10, .05), (20, .05), (30, .8), (40, .8)))  # all within 40 ms
    assert not blink_ok(s((0, .05), (3000, .05), (6000, .05), (7000, .8), (8000, .8)))  # outside the window


def test_a_bare_blink_claim_is_not_enough(client, candidate):
    assert verify_with(client, {"blink": True}).status_code == 422
    assert verify_with(client, {"blink": True, "samples": []}).status_code == 400
    assert verify_with(client, blink_liveness(False)).status_code == 400
    assert verify_with(client, blink_liveness()).status_code == 200


# ---------- 3. password rule on the server ----------

@pytest.mark.parametrize("password", ["Short1a", "alllowercase1", "ALLUPPERCASE1", "NoDigitsHere"])
def test_weak_passwords_are_refused_by_the_server(client, password):
    res = client.post("/api/auth/signup", json=candidate_payload(password=password))
    assert res.status_code == 422, password


def test_a_strong_password_is_accepted(client):
    assert client.post("/api/auth/signup", json=candidate_payload(password="Abcdef12")).status_code == 201


# ---------- 10. candidate names stay hidden until acceptance ----------

def test_names_are_hidden_until_accept_and_numbered_by_rank(client, db, employer, ayesha):
    job = create_job(client, employer[1])
    bilal, bilal_headers = signup(client, candidate_payload(email="bilal@example.com", name="Bilal Ahmed"))
    profile = db.get(CandidateProfile, bilal["id"])
    profile.skills, profile.parsed_cv = ["CSS"], {"skills": ["CSS"]}
    db.commit()
    bilal_app = apply(client, job, bilal_headers)  # the weaker CV applies first
    ayesha_app = apply(client, job, ayesha[1])
    url = f"/api/jobs/{job['id']}/candidates"
    body = client.get(url, headers=employer[1]).json()
    assert [c["candidate"]["name"] for c in body["candidates"]] == ["Candidate #1", "Candidate #2"]
    assert "Ayesha" not in str(body) and "Bilal" not in str(body)

    assert shortlist(client, ayesha_app, employer[1]).status_code == 200
    assert "Ayesha" not in client.get(url, headers=employer[1]).text  # shortlisted is not accepted
    assert respond(client, ayesha_app, ayesha[1], "accept").status_code == 200
    names = [c["candidate"]["name"] for c in client.get(url, headers=employer[1]).json()["candidates"]]
    assert names == ["Ayesha Khan", "Candidate #2"]  # only the one who accepted is named
    assert bilal_app["id"] != ayesha_app["id"]


def test_a_decline_does_not_reveal_the_name(client, employer, ayesha):
    job = create_job(client, employer[1])
    application = apply(client, job, ayesha[1])
    shortlist(client, application, employer[1])
    respond(client, application, ayesha[1], "decline")
    assert "Ayesha" not in client.get("/api/notifications", headers=employer[1]).text
    assert "Ayesha" not in client.get(f"/api/jobs/{job['id']}/candidates", headers=employer[1]).text


# ---------- 11. one response per shortlist, guarded by the database ----------

def test_two_quick_responses_only_one_wins(client, db, employer, ayesha):
    job = create_job(client, employer[1])
    application = apply(client, job, ayesha[1])
    shortlist(client, application, employer[1])
    barrier = threading.Barrier(2)

    def answer(decision):
        barrier.wait()
        return respond(client, application, ayesha[1], decision).status_code

    with ThreadPoolExecutor(2) as pool:
        codes = sorted(pool.map(answer, ["accept", "decline"]))
    assert codes == [200, 409]
    with TestingSession() as s:
        rows = s.scalars(select(ApplicationStatusEvent).where(
            ApplicationStatusEvent.application_id == application["id"],
            ApplicationStatusEvent.status.in_(["accepted", "declined_by_candidate"]))).all()
        assert len(rows) == 1
    assert len(client.get("/api/notifications", headers=employer[1]).json()) == 1


def test_the_database_refuses_a_second_response(client, db, employer, ayesha):
    job = create_job(client, employer[1])
    application = apply(client, job, ayesha[1])
    shortlist(client, application, employer[1])
    assert respond(client, application, ayesha[1], "accept").status_code == 200
    db.add(ApplicationStatusEvent(id="hist-dup", application_id=application["id"], status="declined_by_candidate"))
    with pytest.raises(IntegrityError):  # no application code in the way: the index itself says no
        db.commit()
    db.rollback()
