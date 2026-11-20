from typing import Literal

from pydantic import Field

from app.schemas.base import CamelModel
from app.schemas.cv import EducationModel, ExperienceModel, ProjectModel


class RespondIn(CamelModel):
    decision: Literal["accept", "decline"]
    note: str | None = Field(default=None, max_length=500)


class HistoryItem(CamelModel):
    status: str
    at: int
    employer_message: str | None = None
    candidate_note: str | None = None


class EmployerContact(CamelModel):
    name: str
    company: str | None
    email: str


class MyApplication(CamelModel):
    """A candidate's own application. `employer` is filled in only after they accept."""

    id: str
    job_id: str
    job_title: str
    company: str
    status: str
    employer_message: str | None
    candidate_note: str | None
    applied_at: int
    updated_at: int
    history: list[HistoryItem]
    employer: EmployerContact | None = None


class NotificationOut(CamelModel):
    id: str
    type: str
    title: str
    body: str
    link: str
    created_at: int
    read_at: int | None
    read: bool


class UnreadCount(CamelModel):
    count: int


class EmployerCVOut(CamelModel):
    """The parsed CV an employer may read. No name, email, phone, LinkedIn or GitHub, and no
    interview data."""

    summary: str
    skills: list[str]
    other_skills: list[str]
    education: list[EducationModel]
    experience: list[ExperienceModel]
    projects: list[ProjectModel]
    certifications: list[str]
    experience_years: float


class CVFileInfo(CamelModel):
    name: str
    size: int
    content_type: str
    uploaded_at: int


class ApplicantContact(CamelModel):
    name: str
    email: str
    phone: str | None = None


class ApplicationCV(CamelModel):
    """`file` and `contact` appear only after the candidate accepts the shortlist."""

    application_id: str
    status: str
    cv: EmployerCVOut
    file: CVFileInfo | None = None
    contact: ApplicantContact | None = None
