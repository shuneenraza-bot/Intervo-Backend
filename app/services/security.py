"""Password hashing (argon2 via pwdlib) and JWT tokens (PyJWT): full access tokens and 5-minute face-pending tokens."""

from datetime import datetime, timedelta, timezone

import jwt
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher

from app.config import settings

ALGORITHM = "HS256"

_password_hash = PasswordHash((Argon2Hasher(),))


def hash_password(password: str) -> str:
    return _password_hash.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        return _password_hash.verify(password, hashed)
    except Exception:  # unknown or corrupt hash format
        return False


SCOPE_FULL = "full"
SCOPE_FACE_PENDING = "face_pending"
FACE_PENDING_MINUTES = 5


def create_access_token(user_id: str, role: str, scope: str = SCOPE_FULL) -> str:
    """A "full" token opens every endpoint. A "face_pending" token (5 minutes) only opens the
    face enrol/verify step that finishes signing in."""
    now = datetime.now(timezone.utc)
    minutes = FACE_PENDING_MINUTES if scope == SCOPE_FACE_PENDING else settings.jwt_expire_minutes
    payload = {
        "sub": user_id,
        "role": role,
        "scope": scope,
        "iat": now,
        "exp": now + timedelta(minutes=minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict | None:
    """Returns the token payload, or None if the token is invalid or expired."""
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None
