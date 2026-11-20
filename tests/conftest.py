"""Test setup. Tests run against a separate database, "intervo_test", never the real one.

The URL is TEST_DATABASE_URL if set, otherwise DATABASE_URL with the database name
replaced by "intervo_test". The database is created automatically if it doesn't exist.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db import Base
from app.deps import get_db
from app.main import app
from app.models import ScoringRules

TEST_DB_NAME = "intervo_test"

test_url = (
    make_url(settings.test_database_url)
    if settings.test_database_url
    else make_url(settings.database_url).set(database=TEST_DB_NAME)
)
if "test" not in (test_url.database or ""):
    raise RuntimeError(f'Refusing to run tests against "{test_url.database}": the database name must contain "test".')


def _create_database_if_missing() -> None:
    if test_url.get_backend_name() != "postgresql":
        return
    admin = create_engine(test_url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        exists = conn.scalar(text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": test_url.database})
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{test_url.database}"'))
    admin.dispose()


_create_database_if_missing()
engine = create_engine(test_url)
TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture(scope="session", autouse=True)
def schema():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture(autouse=True)
def clean_tables(schema):
    """Every test starts with empty tables plus the scoring rules row."""
    with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())
    with TestingSession() as session:
        session.add(ScoringRules(id=1, data={"faceThreshold": 0.55}))
        session.commit()


@pytest.fixture(autouse=True)
def storage_dir(tmp_path, monkeypatch):
    """CV files go to a temp folder, never the real storage/."""
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path / "storage"))
    return tmp_path / "storage" / "cvs"


@pytest.fixture
def db():
    with TestingSession() as session:
        yield session


@pytest.fixture
def client():
    def override_get_db():
        with TestingSession() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ---------- helpers ----------

PASSWORD = "Demo@1234"


def face_template(offset: float = 0.0) -> dict:
    """A 276-number landmark template. `offset` shifts every value, lowering similarity."""
    return {"v": 2, "method": "landmarks", "features": [round(0.3 + (i % 23) * 0.05 + offset, 4) for i in range(276)]}


def candidate_payload(**overrides) -> dict:
    return {"role": "candidate", "name": "Ayesha Khan", "email": "ayesha@example.com",
            "password": PASSWORD, "dataConsent": True, **overrides}


def employer_payload(**overrides) -> dict:
    return {"role": "employer", "name": "Hira Malik", "email": "hr@example.com",
            "company": "Northstar Digital", "password": PASSWORD, **overrides}


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def finish_signin(client, pending: dict, offset: float = 0.0) -> dict:
    """The face step with a pending-token response: enrol if no face yet, else verify.
    Returns the full-token body {token, user}."""
    headers = bearer(pending["pendingToken"])
    if pending["faceEnrolled"]:
        res = client.post("/api/auth/face/verify", headers=headers,
                          json={"template": face_template(offset), "liveness": {"blink": True}})
    else:
        res = client.post("/api/auth/face/enroll", headers=headers, json={"template": face_template(offset)})
    assert res.status_code == 200, res.text
    return res.json()


def signup_full(client, payload: dict) -> dict:
    """Sign up, then enrol the face. Returns {token, user} with a full token."""
    res = client.post("/api/auth/signup", json=payload)
    assert res.status_code == 201, res.text
    return finish_signin(client, res.json())


def sign_in(client, email: str, role: str = "candidate", password: str = PASSWORD, offset: float = 0.0) -> dict:
    """Password step, then the face step. Returns {token, user}."""
    res = client.post("/api/auth/login", json={"email": email, "role": role, "password": password})
    assert res.status_code == 200, res.text
    return finish_signin(client, res.json(), offset)


@pytest.fixture
def candidate(client):
    """A signed-up candidate with a face enrolled. Returns {token, user} (full token)."""
    return signup_full(client, candidate_payload())
