"""Two-factor sign-in: password first, then face. Neither alone gives access."""

import math
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import new_id
from app.models import CandidateProfile, ScoringRules, User
from app.schemas.auth import FaceVerifyRequest, LandmarkTemplate, LoginRequest, SignupRequest
from app.services.face import DEFAULT_FACE_THRESHOLD, compare_geometry, is_landmark_template
from app.services.security import hash_password, verify_password

MAX_PASSWORD_ATTEMPTS = 5
LOCKOUT_SECONDS = 60
MAX_FACE_ATTEMPTS = 3
FACE_LOCKOUT_SECONDS = 300
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


def _check_not_locked(user: User, now: datetime, db: Session) -> None:
    if user.locked_until is None:
        return
    remaining = (_aware(user.locked_until) - now).total_seconds()
    if remaining > 0:
        db.rollback()
        raise _too_many_attempts(math.ceil(remaining))


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
    """Creates the account without a face. It can't be used until the face step enrols one."""
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

    user = User(
        id=new_id("emp" if body.role == "employer" else "cand"),
        role=body.role,
        name=name,
        email=body.email,
        password_hash=hash_password(body.password),
        company=company if body.role == "employer" else None,
    )
    if body.role == "candidate":
        user.profile = CandidateProfile(skills=[], share_with_employers=False, consent_at=_now())
    db.add(user)
    try:
        db.commit()
    except IntegrityError:  # two sign-ups with the same email at the same moment
        db.rollback()
        raise conflict from None
    db.refresh(user)
    return user


def login(db: Session, body: LoginRequest) -> User:
    """Step 1: check the password. The caller turns the result into a face-pending token."""
    user = find_account(db, body.email, body.role, lock=True)
    now = _now()

    # Lockout (60 s after 5 wrong passwords, 5 min after 3 wrong faces) blocks this step.
    _check_not_locked(user, now, db)
    user.locked_until = None

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

    # A fresh password step starts a fresh set of 3 face attempts.
    user.failed_password_attempts = 0
    user.failed_face_attempts = 0
    db.commit()
    db.refresh(user)
    return user


def _lock_user(db: Session, user_id: str) -> User:
    user = db.scalars(select(User).where(User.id == user_id).with_for_update()).one()
    db.refresh(user)
    return user


def _finish(db: Session, user: User, method: str) -> User:
    user.failed_face_attempts = 0
    user.last_login_at = _now()
    user.last_login_method = method
    db.commit()
    db.refresh(user)
    return user


def verify_face(db: Session, pending_user: User, body: FaceVerifyRequest) -> User:
    """Step 2 for an enrolled account: blink liveness plus a template match."""
    user = _lock_user(db, pending_user.id)
    now = _now()
    _check_not_locked(user, now, db)
    if user.failed_face_attempts >= MAX_FACE_ATTEMPTS:
        db.rollback()
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail="Too many failed face attempts. Enter your password again to continue.",
        )
    if not is_landmark_template(user.face_template):
        db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="No face is enrolled for this account. Enrol your face first.")
    if not body.liveness.blink:
        db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Blink check failed. Blink naturally and try again.")

    similarity = compare_geometry(body.template.features, user.face_template["features"])
    if similarity < face_threshold(db):
        user.failed_face_attempts += 1
        left = MAX_FACE_ATTEMPTS - user.failed_face_attempts
        if left <= 0:
            user.locked_until = now + timedelta(seconds=FACE_LOCKOUT_SECONDS)
        db.commit()
        if left <= 0:
            raise _too_many_attempts(FACE_LOCKOUT_SECONDS)
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail=f"Face didn't match this account. {left} {'attempt' if left == 1 else 'attempts'} left.",
        )
    return _finish(db, user, "face")


def enrol_face_pending(db: Session, pending_user: User, template: LandmarkTemplate) -> User:
    """Step 2 for an account without a face: enrol it, which completes the sign-in."""
    user = _lock_user(db, pending_user.id)
    if is_landmark_template(user.face_template):
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, detail="A face is already enrolled. Verify it instead.")
    user.face_template = template.model_dump()
    user.face_enrolled_at = _now()
    return _finish(db, user, "face" if user.last_login_at else "signup")


def enrol_face(db: Session, user: User, template: LandmarkTemplate) -> User:
    """Re-enrol (replace) the face of a fully signed-in user."""
    user.face_template = template.model_dump()
    user.face_enrolled_at = _now()
    user.failed_face_attempts = 0
    db.commit()
    db.refresh(user)
    return user
