from typing import Literal

from pydantic import Field, field_validator

from app.models import Application, Job
from app.schemas.base import CamelModel, to_ms
from app.services.catalog import weighted_skills

JobStatus = Literal["open", "closed"]
ApplicationStatus = Literal["new", "shortlisted", "declined"]


class WeightedSkill(CamelModel):
    name: str
    weight: int = Field(ge=1, le=3)


class SuccessCriteria(CamelModel):
    min_score: int = Field(default=0, ge=0, le=100)
    min_match: int = Field(default=0, ge=0, le=100)
    notes: str = ""


class JobIn(CamelModel):
    """The whole Job, as the frontend sends it. id, employerId, company and createdAt are
    set by the server, so they're ignored if present."""

    title: str = Field(min_length=1, max_length=160)
    role_id: str
    description: str = ""
    location: str = Field(default="", max_length=120)
    mode: Literal["On-site", "Hybrid", "Remote"]
    level: str = Field(default="", max_length=60)
    type: str = Field(default="", max_length=60)
    status: JobStatus = "open"
    skills: list[WeightedSkill] = Field(default_factory=list, max_length=50)
    success: SuccessCriteria = Field(default_factory=SuccessCriteria)

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Give the job a title.")
        return v.strip()


class JobStatusIn(CamelModel):
    status: JobStatus


class JobOut(CamelModel):
    id: str
    employer_id: str | None
    company: str
    title: str
    role_id: str
    description: str
    location: str
    mode: str
    level: str
    type: str
    status: str
    created_at: int
    skills: list[WeightedSkill]
    success: SuccessCriteria
    applicant_count: int | None = None  # only filled in for the job's owner

    @classmethod
    def from_job(cls, job: Job, applicant_count: int | None = None) -> "JobOut":
        return cls(
            id=job.id, employer_id=job.employer_id, company=job.company, title=job.title,
            role_id=job.role_id, description=job.description, location=job.location, mode=job.mode,
            level=job.level, type=job.type, status=job.status, created_at=to_ms(job.created_at),
            skills=weighted_skills(job.skills),
            success=SuccessCriteria(min_score=job.min_score, min_match=job.min_match, notes=job.success_notes),
            applicant_count=applicant_count,
        )


class ApplyIn(CamelModel):
    consent: bool = False


class ApplicationStatusIn(CamelModel):
    status: ApplicationStatus


class ApplicationOut(CamelModel):
    id: str
    job_id: str
    candidate_id: str
    date: int
    consent: bool
    status: str

    @classmethod
    def from_application(cls, application: Application) -> "ApplicationOut":
        return cls(
            id=application.id, job_id=application.job_id, candidate_id=application.candidate_id,
            date=to_ms(application.created_at), consent=application.consent, status=application.status,
        )


class JobsResponse(CamelModel):
    jobs: list[JobOut]
    applications: list[ApplicationOut]
