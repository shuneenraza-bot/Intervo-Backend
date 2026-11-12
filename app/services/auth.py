"""Sign-up, sign-in (password or Face ID) and face enrolment."""

import math
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import new_id
from app.models import CandidateProfile, ScoringRules, User
from app.schemas.auth import LandmarkTemplate, LoginRequest, SignupRequest
from app.services.face import DEFAULT_FACE_THRESHOLD, compare_geometry, is_landmark_template
from app.services.security import hash_password, verify_password

MAX_PASSWORD_ATTEMPTS = 5
LOCKOUT_SECONDS = 60
MAX_FACE_ATTEMPTS = 3
MIN_PASSWORD_LENGTH = 8


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _too_many_attempts(seconds: int) -> HTTPException:
    return HTTPException(
        status.HTTP_429_TOO_MANY_REQUESTS,
        detail=f"Too many attempts. Try again in {seconds} seconds.",
        headers={"Retry-After": str(seconds)},
    )


def find_account(db: Session, email: str, role: str, *, lock: bool = False) -> User:
    """The account for an email + role tab. The 404 never reveals the account's real role."""
    query = select(User).where(User.email == email)
    if lock:
        query = query.with_for_update()  # serialise attempt counting per account
    user = db.scalars(query).first()
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No account found with this email.")
    if user.role != role:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"No {role} account found with this email.")
    return user


def face_threshold(db: Session) -> float:
    rules = db.get(ScoringRules, 1)
    value = (rules.data or {}).get("faceThreshold") if rules else None
    return float(value) if isinstance(value, (int, float)) else DEFAULT_FACE_THRESHOLD


def signup(db: Session, body: SignupRequest) -> User:
    name = body.name.strip()
    company = (body.company or "").strip()
    if len(name) < 3:
        raise HTTPException(422, detail="Enter your full name.")
    if len(body.password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(422, detail=f"Use a password with at least {MIN_PASSWORD_LENGTH} characters.")
    if body.role == "employer" and len(company) < 2:
        raise HTTPException(422, detail="Enter your company name.")
    if body.role == "candidate" and not body.data_consent:
        raise HTTPException(422, detail="Consent is needed to process your CV and interview answers.")

    conflict = HTTPException(status.HTTP_409_CONFLICT, detail="An account with this email already exists.")
    if db.scalars(select(User.id).where(User.email == body.email)).first():
        raise conflict

    now = _now()
    template = None
    if body.face is not None:
        t = body.face.template
        template = t.model_dump() if isinstance(t, LandmarkTemplate) else t

    user = User(
        id=new_id("emp" if body.role == "employer" else "cand"),
        role=body.role,
        name=name,
        email=body.email,
        password_hash=hash_password(body.password),
        company=company if body.role == "employer" else None,
        face_template=template,
        face_enrolled_at=now if template is not None else None,
        last_login_at=now,
        last_login_method="signup",
    )
    if body.role == "candidate":
        user.profile = CandidateProfile(skills=[], share_with_employers=False, consent_at=now)
    db.add(user)
    try:
        db.commit()
    except IntegrityError:  # two sign-ups with the same email at the same moment
        db.rollback()
        raise conflict from None
    db.refresh(user)
    return user


def login(db: Session, body: LoginRequest) -> User:
    if (body.password is None) == (body.face_template is None):
        raise HTTPException(422, detail="Sign in with either a password or Face ID.")

    user = find_account(db, body.email, body.role, lock=True)
    now = _now()

    # 60-second lockout after too many wrong passwords blocks every sign-in method.
    if user.locked_until is not None:
        remaining = (_aware(user.locked_until) - now).total_seconds()
        if remaining > 0:
            db.rollback()
            raise _too_many_attempts(math.ceil(remaining))
        user.locked_until = None

    if body.password is not None:
        if not verify_password(body.password, user.password_hash):
            user.failed_password_attempts += 1
            locked = user.failed_password_attempts >= MAX_PASSWORD_ATTEMPTS
            if locked:
                user.failed_password_attempts = 0
                user.locked_until = now + timedelta(seconds=LOCKOUT_SECONDS)
            db.commit()
            if locked:
                raise _too_many_attempts(LOCKOUT_SECONDS)
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Incorrect password.")
        method = "password"
    else:
        if not is_landmark_template(user.face_template):
            db.rollback()
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Face ID isn't set up for this account.")
        # After 3 failed face attempts, Face ID stays locked until a password sign-in succeeds.
        if user.failed_face_attempts >= MAX_FACE_ATTEMPTS:
            db.rollback()
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED,
                detail="Face ID is locked after too many failed attempts. Sign in with your password.",
            )
        similarity = compare_geometry(body.face_template.features, user.face_template["features"])
        if similarity < face_threshold(db):
            user.failed_face_attempts += 1
            db.commit()
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Face didn't match this account.")
        method = "face"

    user.failed_password_attempts = 0
    if method == "password":
        user.failed_face_attempts = 0
    user.last_login_at = now
    user.last_login_method = method
    db.commit()
    db.refresh(user)
    return user


def enrol_face(db: Session, user: User, template: LandmarkTemplate) -> User:
    user.face_template = template.model_dump()
    user.face_enrolled_at = _now()
    user.failed_face_attempts = 0
    db.commit()
    db.refresh(user)
    return user


def remove_face(db: Session, user: User) -> User:
    user.face_template = None
    user.face_enrolled_at = None
    user.failed_face_attempts = 0
    db.commit()
    db.refresh(user)
    return user
