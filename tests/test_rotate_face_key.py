"""scripts/rotate_face_key.py: all templates move to the new key in one transaction."""

import json

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import text

from app.services import face_crypto
from scripts.rotate_face_key import UnreadableTemplate, rotate
from tests.conftest import engine, face_template, sign_in
from tests.test_hardening import raw_face


def read_with(key: bytes, user_id: str):
    return json.loads(Fernet(key).decrypt(raw_face(user_id)["data"].encode()))


def test_every_template_moves_to_the_new_key(client, candidate):
    uid = candidate["user"]["id"]
    new_key = Fernet.generate_key()
    before = raw_face(uid)
    assert rotate(engine, face_crypto._fernet(), new_key) == 1
    assert raw_face(uid) != before
    assert read_with(new_key, uid)["features"] == face_template()["features"]


def test_a_legacy_plain_template_is_encrypted_too(client, candidate):
    uid = candidate["user"]["id"]
    with engine.begin() as conn:
        conn.execute(text("UPDATE users SET face_template = CAST(:t AS jsonb) WHERE id = :i"),
                     {"t": json.dumps(face_template()), "i": uid})
    new_key = Fernet.generate_key()
    rotate(engine, face_crypto._fernet(), new_key)
    assert read_with(new_key, uid)["features"] == face_template()["features"]


def test_one_unreadable_template_changes_nothing(client, candidate):
    uid = candidate["user"]["id"]
    before = raw_face(uid)
    wrong_old = Fernet(Fernet.generate_key())
    with pytest.raises(UnreadableTemplate):
        rotate(engine, wrong_old, Fernet.generate_key())
    assert raw_face(uid) == before
    assert sign_in(client, "ayesha@example.com")["token"]  # still readable with the app's key


def test_the_app_reads_the_rotated_templates_with_the_new_key(client, candidate, monkeypatch):
    new_key = Fernet.generate_key()
    rotate(engine, face_crypto._fernet(), new_key)
    monkeypatch.setattr(face_crypto.settings, "face_encryption_key", new_key.decode())
    face_crypto._fernet.cache_clear()
    try:
        assert sign_in(client, "ayesha@example.com")["token"]
    finally:
        monkeypatch.undo()
        face_crypto._fernet.cache_clear()
