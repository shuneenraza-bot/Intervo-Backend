from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, false
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, JSONType, TimestampMixin

if TYPE_CHECKING:
    from app.models.catalog import JobRole


class User(TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('candidate', 'employer', 'admin')", name="role"),
        CheckConstraint(
            "last_login_method IS NULL OR last_login_method IN ('password', 'face', 'signup')",
            name="last_login_method",
        ),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    role: Mapped[str] = mapped_column(String(20), index=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    company: Mapped[str | None] = mapped_column(String(160))

    # Face ID: landmark template {"v": 2, "method": "landmarks", "features": [...]}
    face_template: Mapped[Any | None] = mapped_column(JSONType)
    face_enrolled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_method: Mapped[str | None] = mapped_column(String(20))

    # Sign-in attempt limits (enforced in app/services/auth.py)
    failed_password_attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    failed_face_attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    profile: Mapped[CandidateProfile | None] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )


class CandidateProfile(TimestampMixin, Base):
    __tablename__ = "candidate_profiles"

    user_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    skills: Mapped[list[str]] = mapped_column(JSONType, default=list)  # skill names
    cv: Mapped[dict[str, Any] | None] = mapped_column(JSONType)  # ParsedCV
    target_role_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("job_roles.id", ondelete="SET NULL"), index=True
    )
    share_with_employers: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="profile")
    target_role: Mapped[JobRole | None] = relationship()
