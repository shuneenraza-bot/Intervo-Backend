"""Candidate-owned data that the employer's suitability score reads: the profile
(skills, CV summary, sharing switch) and finished practice sessions."""

from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.db import new_id
from app.models import CandidateProfile, InterviewSession, JobRole, QuestionTemplate, SessionAnswer, Skill, User
from app.schemas.base import to_ms
from app.schemas.candidate import ProfileIn, ProfileOut, SessionIn

_SESSION_OPTIONS = (
    selectinload(InterviewSession.answers).selectinload(SessionAnswer.skill),
    selectinload(InterviewSession.role),
)


# ---------- profile ----------

def save_profile(db: Session, candidate: User, body: ProfileIn) -> ProfileOut:
    profile = db.get(CandidateProfile, candidate.id)
    if profile is None:
        profile = CandidateProfile(user_id=candidate.id)
        db.add(profile)
    profile.skills = body.skills
    profile.cv = body.cv.model_dump(by_alias=True) if body.cv else None
    profile.share_with_employers = body.share_with_employers
    if body.share_with_employers and profile.consent_at is None:
        profile.consent_at = datetime.now(timezone.utc)
    db.commit()
    return ProfileOut(skills=profile.skills, cv=body.cv, share_with_employers=profile.share_with_employers)


# ---------- sessions ----------

def session_out(session: InterviewSession) -> dict:
    """The candidate's own session in the frontend's Session shape. Answer text and
    follow-ups are not stored by the sync, so they come back empty."""
    return {
        "id": session.id,
        "userId": session.candidate_id,
        "roleId": session.role_id,
        "roleTitle": session.role.title if session.role else "",
        "mode": session.mode,
        "date": to_ms(session.date),
        "score": session.score,
        "answers": [
            {
                "questionId": a.question_id,
                "question": a.question,
                "skill": a.skill.name if a.skill else "",
                "type": a.type,
                "score": a.score,
                "criteria": a.criteria or {},
                "answer": "",
                "reason": a.reason,
                "followUp": None,
                "indicators": a.indicators,
            }
            for a in session.answers
        ],
    }


def _load_session(db: Session, session_id: str) -> InterviewSession | None:
    return db.scalars(
        select(InterviewSession).where(InterviewSession.id == session_id).options(*_SESSION_OPTIONS)
    ).first()


def save_session(db: Session, candidate: User, body: SessionIn) -> tuple[dict, bool]:
    """Stores a finished session. Returns (session, created). Sending a session id this
    candidate already saved returns the stored one unchanged, so a client can safely re-send."""
    taken = HTTPException(status.HTTP_409_CONFLICT, detail="This session id is already in use.")
    if body.id:
        existing = _load_session(db, body.id)
        if existing is not None:
            if existing.candidate_id != candidate.id:
                raise taken
            return session_out(existing), False

    # Names and ids come from the browser's copy of the config, which can differ from the
    # server's: anything the server doesn't know is stored without the link.
    names = {a.skill for a in body.answers}
    skill_ids = {s.name: s.id for s in db.scalars(select(Skill).where(Skill.name.in_(names)))}
    question_ids = {a.question_id for a in body.answers if a.question_id}
    known_questions = (
        set(db.scalars(select(QuestionTemplate.id).where(QuestionTemplate.id.in_(question_ids))))
        if question_ids
        else set()
    )
    role_id = body.role_id if body.role_id and db.get(JobRole, body.role_id) else None

    session = InterviewSession(
        id=body.id or new_id("s"),
        candidate_id=candidate.id,
        role_id=role_id,
        mode=body.mode,
        score=body.score,
        date=datetime.fromtimestamp(body.date / 1000, tz=timezone.utc) if body.date is not None else datetime.now(timezone.utc),
        answers=[
            SessionAnswer(
                id=new_id("ans"),
                skill_id=skill_ids.get(a.skill),
                question_id=a.question_id if a.question_id in known_questions else None,
                position=position,
                question=a.question,
                type=a.type,
                answer="",
                score=a.score,
                criteria=a.criteria,
                indicators=a.indicators,
                reason=a.reason,
            )
            for position, a in enumerate(body.answers)
        ],
    )
    db.add(session)
    try:
        db.commit()
    except IntegrityError:
        # The same id was saved a moment ago by a parallel request.
        db.rollback()
        existing = _load_session(db, session.id)
        if existing is None or existing.candidate_id != candidate.id:
            raise taken from None
        return session_out(existing), False
    return session_out(_load_session(db, session.id)), True
