from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.deps import DbSession, require_role
from app.models import User
from app.schemas.interview import AnswerBody, FollowUpBody, StartIn
from app.services import interview as service

router = APIRouter(tags=["interviews"])
Candidate = Annotated[User, Depends(require_role("candidate"))]


@router.post("/interviews", status_code=status.HTTP_201_CREATED)
def start(body: StartIn, user: Candidate, db: DbSession) -> dict:
    """Plans the questions (weaknesses, CV gaps, role skills, one behavioural) and opens a session."""
    return service.start(db, user, body)


@router.get("/interviews")
def history(user: Candidate, db: DbSession) -> list[dict]:
    return service.list_interviews(db, user)


@router.get("/interviews/{interview_id}")
def detail(interview_id: str, user: Candidate, db: DbSession) -> dict:
    return service.get_interview(db, user, interview_id)


@router.post("/interviews/{interview_id}/answers")
def answer(interview_id: str, body: AnswerBody, user: Candidate, db: DbSession) -> dict:
    return service.answer(db, user, interview_id, body)


@router.post("/interviews/{interview_id}/answers/{answer_id}/follow-up")
def follow_up(interview_id: str, answer_id: str, body: FollowUpBody, user: Candidate, db: DbSession) -> dict:
    return service.follow_up(db, user, interview_id, answer_id, body)


@router.post("/interviews/{interview_id}/finish")
def finish(interview_id: str, user: Candidate, db: DbSession) -> dict:
    return service.finish(db, user, interview_id)


@router.get("/progress")
def progress(user: Candidate, db: DbSession) -> dict:
    return service.progress(db, user)
