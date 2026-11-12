# Intervo Backend

REST API for Intervo, an AI interview coaching platform. It serves the React frontend in `../Intervo-Frontend` and follows the contract in that project's `API.md`.

**Stack:** Python 3.13 · FastAPI · SQLAlchemy 2.0 · PostgreSQL 18 (psycopg 3) · Alembic · pydantic-settings · PyJWT · pwdlib (argon2)

## Setup (Windows PowerShell)

Run these from the project folder.

```powershell
# 1. Virtual environment and packages
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt

# 2. Create .env with a random JWT secret, then type your Postgres password into it
Copy-Item .env.example .env
$secret = python -c "import secrets; print(secrets.token_urlsafe(48))"
(Get-Content .env) -replace 'change-me-to-a-long-random-string', $secret | Set-Content .env -Encoding utf8
notepad .env    # replace YOUR_PASSWORD in DATABASE_URL, save, close

# 3. Create the tables, then load the configuration and demo data
alembic upgrade head
python -m scripts.seed

# 4. Run the server
uvicorn app.main:app --reload --port 8000

# 5. Run the tests (in a second terminal, with the venv activated)
pytest -v
```

If PowerShell refuses to run `Activate.ps1`, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once.

If your Postgres password contains `@ : / # % ?`, URL-encode those characters in `DATABASE_URL` (for example `@` becomes `%40`).

The database `intervo` must already exist. The test database `intervo_test` is created automatically the first time you run `pytest`.

Interactive API docs: http://localhost:8000/docs

## Connecting the frontend

All routes are under `/api`, so the frontend's `.env` needs:

```
VITE_USE_BACKEND=true
VITE_API_URL=http://localhost:8000/api
```

## Endpoints

| Method | Path | Who | Purpose |
|---|---|---|---|
| GET | `/api/health` | public | Server and database check |
| POST | `/api/auth/lookup` | public | Sign-in step 1: does the account exist, is Face ID enabled |
| POST | `/api/auth/signup` | public | Create a candidate or employer account |
| POST | `/api/auth/login` | public | Sign in with a password **or** a face template |
| GET | `/api/auth/me` | signed in | The current user |
| PUT | `/api/auth/face` | signed in | Enrol or replace Face ID. Body: `{ "template": { "v": 2, "method": "landmarks", "features": [...] } }` |
| DELETE | `/api/auth/face` | signed in | Remove Face ID |

`PUT` and `DELETE /api/auth/face` return the updated `User`.

### Sign-in rules

- Password and Face ID are alternatives. The login body holds `password` or `faceTemplate`, never both.
- Face ID compares the live template with the stored one: `similarity = max(0, 1 - mean(|a - b|) / 0.12)`. It is accepted when the similarity is at least `faceThreshold` in the `scoring_rules` row (0.55 after seeding).
- 5 wrong passwords in a row lock all sign-in for that account for 60 seconds. The response is `429` with a `Retry-After` header.
- 3 failed Face ID attempts lock Face ID for that account until a password sign-in succeeds.
- Passwords are stored as argon2 hashes. Tokens are HS256 JWTs that expire after `JWT_EXPIRE_MINUTES`.

### Demo accounts (created by the seed script)

| Role | Email | Password |
|---|---|---|
| Candidate | ayesha@intervo.demo | Demo@1234 |
| Employer | hr@northstar.demo | Demo@1234 |
| Admin | admin@intervo.demo | Admin@1234 |

## Project layout

```
app/
  main.py        FastAPI app, CORS, router registration
  config.py      Settings from .env
  db.py          Engine, session factory, Base, timestamp mixin
  deps.py        get_db, get_current_user, require_role
  models/        SQLAlchemy tables
  schemas/       Pydantic request and response models (camelCase JSON)
  routers/       HTTP endpoints
  services/      Business logic: auth, password and JWT, face comparison
alembic/         Migrations
scripts/seed.py  Configuration and demo data, mirrors the frontend's src/data.js
tests/           pytest suite, runs against the intervo_test database
```

## Database

14 tables, all with `created_at` and `updated_at`:

- **Accounts:** `users`, `candidate_profiles`
- **Admin configuration:** `domains`, `skills`, `job_roles`, `role_skills`, `question_templates`, `evaluation_criteria`, `scoring_rules`
- **Jobs:** `jobs`, `job_skills`, `applications`
- **Interviews:** `interview_sessions`, `session_answers`

IDs are strings (`cand-3f9a1c2b7d4e`, `frontend`, `q1`) because the frontend uses string IDs. The API sends timestamps as Unix epoch milliseconds.

### Changing the schema

Edit the models, then:

```powershell
alembic revision --autogenerate -m "describe the change"
alembic upgrade head
```

Read the generated file in `alembic/versions/` before applying it.

### Protecting a route by role

```python
from fastapi import Depends
from app.deps import require_role

@router.post("/jobs")
def create_job(user: User = Depends(require_role("employer"))):
    ...
```
