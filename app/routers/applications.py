from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse

from app.deps import DbSession, require_role
from app.models import User
from app.schemas.applications import ApplicationCV, MyApplication, RespondIn
from app.services import applications as service
from app.services import cv_files

router = APIRouter(tags=["applications"])

Employer = Annotated[User, Depends(require_role("employer"))]
Candidate = Annotated[User, Depends(require_role("candidate"))]


@router.get("/applications/mine", response_model=list[MyApplication])
def mine(user: Candidate, db: DbSession):
    """The candidate's own applications. The employer's contact card appears only after they accept."""
    return service.my_applications(db, user)


@router.post("/applications/{application_id}/respond", response_model=MyApplication)
def respond(application_id: str, body: RespondIn, user: Candidate, db: DbSession):
    """Accept or decline a shortlist. Allowed once, while the status is shortlisted."""
    return service.respond(db, application_id, user, body.decision, body.note)


@router.get("/applications/{application_id}/cv", response_model=ApplicationCV)
def application_cv(application_id: str, user: Employer, db: DbSession):
    """The parsed CV the candidate applied with, without contact details. After they accept, the
    file info and contact card are included. Job owner and consenting applicants only."""
    return service.application_cv(db, application_id, user)


@router.get("/applications/{application_id}/cv-file")
def application_cv_file(application_id: str, user: Employer, db: DbSession):
    """The original CV file, only after the candidate accepted the shortlist (PDFs open inline)."""
    row = service.application_cv_file(db, application_id, user)
    pdf = row.content_type == "application/pdf"
    return FileResponse(cv_files.path_of(row), media_type=row.content_type, filename=row.file_name,
                        content_disposition_type="inline" if pdf else "attachment",
                        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})
