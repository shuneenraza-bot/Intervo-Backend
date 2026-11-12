from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from app.deps import CurrentUser, DbSession, require_role
from app.models import User
from app.schemas.jobs import (
    ApplicationOut,
    ApplicationStatusIn,
    ApplyIn,
    JobIn,
    JobOut,
    JobsResponse,
    JobStatusIn,
)
from app.services import jobs as job_service
from app.services.catalog import load_config

router = APIRouter(tags=["jobs"])

Employer = Annotated[User, Depends(require_role("employer"))]
Candidate = Annotated[User, Depends(require_role("candidate"))]


@router.get("/config")
def get_config(user: CurrentUser, db: DbSession) -> dict:
    """Admin configuration in the same shape as `config` in the frontend's src/data.js."""
    return load_config(db)


@router.get("/jobs", response_model=JobsResponse)
def list_jobs(user: CurrentUser, db: DbSession):
    return job_service.list_jobs(db, user)


@router.post("/jobs", response_model=JobOut, status_code=status.HTTP_201_CREATED)
def create_job(body: JobIn, user: Employer, db: DbSession):
    return job_service.create_job(db, user, body)


@router.put("/jobs/{job_id}", response_model=JobOut)
def update_job(job_id: str, body: JobIn, user: Employer, db: DbSession):
    return job_service.update_job(db, job_id, user, body)


@router.patch("/jobs/{job_id}/status", response_model=JobOut)
def set_job_status(job_id: str, body: JobStatusIn, user: Employer, db: DbSession):
    """Close or reopen a job without sending the whole posting."""
    return job_service.set_job_status(db, job_id, user, body.status)


@router.post("/jobs/{job_id}/apply", response_model=ApplicationOut, status_code=status.HTTP_201_CREATED)
def apply(job_id: str, body: ApplyIn, user: Candidate, db: DbSession):
    return job_service.apply_to_job(db, job_id, user, body.consent)


@router.delete("/jobs/{job_id}/apply", status_code=status.HTTP_204_NO_CONTENT)
def withdraw(job_id: str, user: Candidate, db: DbSession):
    job_service.withdraw_application(db, job_id, user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/jobs/{job_id}/candidates")
def candidates(job_id: str, user: Employer, db: DbSession) -> dict:
    """Ranked applicants with an explainable suitability score (job owner only)."""
    return job_service.ranked_candidates(db, job_id, user)


# API.md uses PATCH /applications/{id}; the /status form is an alias.
@router.patch("/applications/{application_id}", response_model=ApplicationOut)
@router.patch("/applications/{application_id}/status", response_model=ApplicationOut, include_in_schema=False)
def set_application_status(application_id: str, body: ApplicationStatusIn, user: Employer, db: DbSession):
    return job_service.set_application_status(db, application_id, user, body.status)
