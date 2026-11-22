"""Encryption of face templates at rest (Fernet: AES-128-CBC + HMAC-SHA256).

The key is FACE_ENCRYPTION_KEY (a Fernet key). If it is not set, a key is derived from
JWT_SECRET so existing installs keep working; set a separate key in production. A template
stored by an older version (plain JSON) is still read and is encrypted the next time it is
saved, or by the migration that ships with this change."""

import base64
import hashlib
import json
from functools import lru_cache
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

MARK = "enc"


@lru_cache
def _fernet() -> Fernet:
    key = (settings.face_encryption_key or "").strip()
    if key:
        return Fernet(key.encode())
    derived = hashlib.sha256(b"intervo-face-template:" + settings.jwt_secret.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(derived))


def is_encrypted(value: Any) -> bool:
    return isinstance(value, dict) and value.get(MARK) == 1 and isinstance(value.get("data"), str)


def encrypt_template(template: Any) -> Any:
    """A plain template -> {"enc": 1, "data": "<token>"}. None and already-encrypted values pass through."""
    if template is None or is_encrypted(template):
        return template
    token = _fernet().encrypt(json.dumps(template, separators=(",", ":")).encode())
    return {MARK: 1, "data": token.decode()}


def decrypt_template(value: Any) -> Any:
    """The inverse. Plain (legacy) values are returned as they are; an unreadable token becomes None."""
    if not is_encrypted(value):
        return value
    try:
        return json.loads(_fernet().decrypt(value["data"].encode()))
    except (InvalidToken, ValueError):
        return None
