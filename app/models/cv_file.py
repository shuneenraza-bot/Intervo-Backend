from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, TimestampMixin


class CvFile(TimestampMixin, Base):
    """An uploaded original CV. The bytes live under storage/cvs/<storage_name>; created_at is the
    upload date. A candidate's current CV is candidate_profiles.cv_file_id; older files stay only
    while an application still points at them (the snapshot that employer received)."""

    __tablename__ = "cv_files"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(40), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    file_name: Mapped[str] = mapped_column(String(255))  # the name the candidate uploaded
    content_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(Integer)
    storage_name: Mapped[str] = mapped_column(String(80), unique=True)  # random, never the user's name
