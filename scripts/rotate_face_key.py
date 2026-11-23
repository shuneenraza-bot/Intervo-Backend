"""Moves every stored face template to a new encryption key.

Generates a new Fernet key, re-encrypts all face templates from the current key (FACE_ENCRYPTION_KEY,
or the key derived from JWT_SECRET when that is unset) to the new one in ONE transaction, and prints
only the line to add to .env:

    FACE_ENCRYPTION_KEY=...

Order (the server must not run while this happens, or it writes with the old key):
    1. stop the server
    2. python -m scripts.rotate_face_key
    3. put the printed line in .env (replace an existing FACE_ENCRYPTION_KEY line)
    4. start the server

If a template cannot be read with the current key, nothing is changed and no key is printed.
Run from the project root. `--test-db` runs against the test database (intervo_test) instead.
"""

import sys

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url

from app.config import settings
from app.services import face_crypto


class UnreadableTemplate(Exception):
    pass


def rotate(engine: Engine, old: Fernet, new_key: bytes) -> int:
    """Re-encrypts every face template in one transaction. Returns how many were changed."""
    new = Fernet(new_key)
    changed = 0
    with engine.begin() as conn:  # any exception rolls everything back
        rows = conn.execute(
            text("SELECT id, face_template FROM users WHERE face_template IS NOT NULL FOR UPDATE")
        ).all()
        for user_id, value in rows:
            if face_crypto.is_encrypted(value):
                try:
                    plain = old.decrypt(value["data"].encode())
                except InvalidToken:
                    raise UnreadableTemplate(user_id) from None
            else:  # a legacy plain template: encrypt it now
                plain = face_crypto.json.dumps(value, separators=(",", ":")).encode()
            token = new.encrypt(plain).decode()
            conn.execute(
                text("UPDATE users SET face_template = CAST(:v AS jsonb) WHERE id = :i"),
                {"v": face_crypto.json.dumps({face_crypto.MARK: 1, "data": token}), "i": user_id},
            )
            changed += 1
    return changed


def main(argv: list[str]) -> int:
    url = make_url(settings.database_url)
    if "--test-db" in argv:
        url = make_url(settings.test_database_url) if settings.test_database_url else url.set(database="intervo_test")
    engine = create_engine(url)
    new_key = Fernet.generate_key()
    try:
        changed = rotate(engine, face_crypto._fernet(), new_key)
    except UnreadableTemplate as err:
        print(f"Stopped, nothing changed: the template of user {err} cannot be read with the current key. "
              "Check FACE_ENCRYPTION_KEY / JWT_SECRET.", file=sys.stderr)
        return 1
    print(f"Re-encrypted {changed} face template(s).", file=sys.stderr)
    print(f"FACE_ENCRYPTION_KEY={new_key.decode()}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
