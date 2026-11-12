from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, JSONType, TimestampMixin

if TYPE_CHECKING:
    from app.models.catalog import JobRole, Skill
    from app.models.user import User


class InterviewSession(TimestampMixin, Base):
    __tablename__ = "interview_sessions"
    __table_args__ = (
        CheckConstraint("mode IN ('text', 'voice', 'video')", name="mode"),
        CheckConstraint("score BETWEEN 0 AND 100", name="score"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    candidate_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    role_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("job_roles.id", ondelete="SET NULL"), index=True
    )
    mode: Mapped[str] = mapped_column(String(20), default="text", server_default="text")
    score: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    date: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    candidate: Mapped[User] = relationship()
    role: Mapped[JobRole | None] = relationship()
    answers: Mapped[list[SessionAnswer]] = relationship(
        back_populates="session", cascade="all, delete-orphan", order_by="SessionAnswer.position"
    )


class SessionAnswer(TimestampMixin, Base):
    __tablename__ = "session_answers"
    __table_args__ = (
        CheckConstraint("type IN ('technical', 'behavioral')", name="type"),
        CheckConstraint("score BETWEEN 0 AND 100", name="score"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("interview_sessions.id", ondelete="CASCADE"), index=True
    )
    skill_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("skills.id", ondelete="SET NULL"), index=True
    )
    question_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("question_templates.id", ondelete="SET NULL"), index=True
    )
    position: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    question: Mapped[str] = mapped_column(Text)
    type: Mapped[str] = mapped_column(String(20))
    answer: Mapped[str] = mapped_column(Text, default="", server_default="")
    score: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    criteria: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)  # {"relevance": 78, ...}
    indicators: Mapped[dict[str, Any] | None] = mapped_column(JSONType)  # video-mode cues
    reason: Mapped[str | None] = mapped_column(String(20))  # weakness | gap | role | general
    follow_up: Mapped[dict[str, Any] | None] = mapped_column(JSONType)  # {question, answer, before}

    session: Mapped[InterviewSession] = relationship(back_populates="answers")
    skill: Mapped[Skill | None] = relationship()
