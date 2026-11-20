from typing import Literal

from pydantic import Field

from app.schemas.base import CamelModel


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
