from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, false, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.catalog import JobRole, Skill
    from app.models.user import User


class Job(TimestampMixin, Base):
    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint("status IN ('open', 'closed')", name="status"),
        CheckConstraint("mode IN ('On-site', 'Hybrid', 'Remote')", name="mode"),
        CheckConstraint("min_match BETWEEN 0 AND 100", name="min_match"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    # NULL for listings that aren't owned by an Intervo employer account
    employer_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    company: Mapped[str] = mapped_column(String(160))  # copied from the employer at creation
    title: Mapped[str] = mapped_column(String(160))
    role_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("job_roles.id", ondelete="RESTRICT"), index=True
    )
    location: Mapped[str] = mapped_column(String(120), default="", server_default="")
    mode: Mapped[str] = mapped_column(String(20))
    level: Mapped[str] = mapped_column(String(60), default="", server_default="")
    type: Mapped[str] = mapped_column(String(60), default="", server_default="")
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    status: Mapped[str] = mapped_column(String(20), default="open", server_default="open", index=True)
    min_match: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    success_notes: Mapped[str] = mapped_column(Text, default="", server_default="")

    employer: Mapped[User | None] = relationship()
    role: Mapped[JobRole] = relationship()
    skills: Mapped[list[JobSkill]] = relationship(back_populates="job", cascade="all, delete-orphan")
    applications: Mapped[list[Application]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )


class JobSkill(TimestampMixin, Base):
    __tablename__ = "job_skills"
    __table_args__ = (CheckConstraint("weight BETWEEN 1 AND 3", name="weight"),)

    job_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True
    )
    skill_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("skills.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    weight: Mapped[int] = mapped_column(Integer, default=2, server_default="2")

    job: Mapped[Job] = relationship(back_populates="skills")
    skill: Mapped[Skill] = relationship()


class Application(TimestampMixin, Base):
    """created_at is the application date. Flow: applied -> shortlisted -> accepted |
    declined_by_candidate; the employer can also set not_progressing. Every change is kept in
    application_status_history."""

    __tablename__ = "applications"
    __table_args__ = (
        UniqueConstraint("job_id", "candidate_id"),
        CheckConstraint(
            "status IN ('applied', 'shortlisted', 'accepted', 'declined_by_candidate', 'not_progressing')",
            name="status",
        ),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    job_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("jobs.id", ondelete="CASCADE"), index=True
    )
    candidate_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    consent: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    status: Mapped[str] = mapped_column(String(30), default="applied", server_default="applied")

    job: Mapped[Job] = relationship(back_populates="applications")
    candidate: Mapped[User] = relationship()
    history: Mapped[list[ApplicationStatusEvent]] = relationship(
        back_populates="application", cascade="all, delete-orphan",
        order_by="ApplicationStatusEvent.created_at, ApplicationStatusEvent.id",
    )


class ApplicationStatusEvent(Base):
    """One row per status change, with the employer's message or the candidate's note."""

    __tablename__ = "application_status_history"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    application_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("applications.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(30))
    employer_message: Mapped[str | None] = mapped_column(Text)
    candidate_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    application: Mapped[Application] = relationship(back_populates="history")
