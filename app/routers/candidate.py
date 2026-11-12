from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from app.deps import DbSession, require_role
from app.models import User
from app.schemas.candidate import ProfileIn, ProfileOut, SessionIn
from app.services import candidate as candidate_service

router = APIRouter(tags=["candidate"])

Candidate = Annotated[User, Depends(require_role("candidate"))]


@router.put("/profile", response_model=ProfileOut)
def save_profile(body: ProfileIn, user: Candidate, db: DbSession):
    """Saves the skills, CV summary and sharing switch the employer's suitability score reads."""
    return candidate_service.save_profile(db, user, body)


@router.post("/sessions", status_code=status.HTTP_201_CREATED)
def save_session(body: SessionIn, user: Candidate, db: DbSession, response: Response) -> dict:
    """Saves a finished practice session. 200 instead of 201 when this id was already saved."""
    session, created = candidate_service.save_session(db, user, body)
    if not created:
        response.status_code = status.HTTP_200_OK
    return session
