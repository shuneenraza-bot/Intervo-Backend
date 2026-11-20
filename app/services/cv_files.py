"""Original CV files on disk (storage/cvs/) and their rows in cv_files.

Files are written with a random name, never the uploaded one. A file is deleted when nothing
needs it any more: not the candidate's current CV and not the snapshot of any application."""

import mimetypes
import secrets
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import new_id
from app.models import Application, CandidateProfile, CvFile

ROOT = Path(__file__).resolve().parents[2]
CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain; charset=utf-8",
}


def cv_dir() -> Path:
    base = Path(settings.storage_dir)
    return (base if base.is_absolute() else ROOT / base) / "cvs"


def path_of(cv_file: CvFile) -> Path:
    return cv_dir() / cv_file.storage_name  # storage_name is generated here, never user input


def _remove(names: list[str]) -> None:
    for name in names:
        try:
            (cv_dir() / name).unlink(missing_ok=True)
        except OSError:
            pass  # a locked or missing file must not break the request


def add_file(db: Session, user_id: str, file_name: str, data: bytes) -> CvFile:
    """Writes the bytes and adds the row (not committed). Call after the CV text was validated."""
    ext = Path(file_name).suffix.lower()
    content_type = CONTENT_TYPES.get(ext) or mimetypes.guess_type(file_name)[0] or "application/octet-stream"
    storage_name = secrets.token_hex(24) + (ext if ext in CONTENT_TYPES else "")
    cv_dir().mkdir(parents=True, exist_ok=True)
    (cv_dir() / storage_name).write_bytes(data)
    row = CvFile(id=new_id("cvf"), user_id=user_id, file_name=file_name, content_type=content_type,
                 size_bytes=len(data), storage_name=storage_name)
    db.add(row)
    db.flush()
    return row


def _in_use(db: Session, file_id: str) -> bool:
    return (
        db.scalars(select(CandidateProfile.user_id).where(CandidateProfile.cv_file_id == file_id)).first() is not None
        or db.scalars(select(Application.id).where(Application.cv_file_id == file_id)).first() is not None
    )


def discard_if_unused(db: Session, file_id: str | None) -> list[str]:
    """Deletes the row if nothing uses it and returns the storage name to remove after commit."""
    if not file_id:
        return []
    row = db.get(CvFile, file_id)
    if row is None or _in_use(db, file_id):
        return []
    db.delete(row)
    db.flush()
    return [row.storage_name]


def remove_stored(names: list[str]) -> None:
    """Deletes the bytes. Only call after the database commit succeeded."""
    _remove(names)


def user_storage_names(db: Session, user_id: str) -> list[str]:
    return list(db.scalars(select(CvFile.storage_name).where(CvFile.user_id == user_id)))
