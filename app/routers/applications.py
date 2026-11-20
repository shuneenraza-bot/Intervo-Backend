from typing import Annotated

from fastapi import APIRouter, Depends

from app.deps import DbSession, require_role
from app.models import User
from app.schemas.applications import MyApplication, RespondIn
from app.services import applications as service

router = APIRouter(tags=["applications"])

Candidate = Annotated[User, Depends(require_role("candidate"))]


@router.get("/applications/mine", response_model=list[MyApplication])
def mine(user: Candidate, db: DbSession):
    """The candidate's own applications. The employer's contact card appears only after they accept."""
    return service.my_applications(db, user)


@router.post("/applications/{application_id}/respond", response_model=MyApplication)
def respond(application_id: str, body: RespondIn, user: Candidate, db: DbSession):
    """Accept or decline a shortlist. Allowed once, while the status is shortlisted."""
    return service.respond(db, application_id, user, body.decision, body.note)
