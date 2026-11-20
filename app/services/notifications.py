"""In-app notifications. `notify` only adds the row: the caller commits it together with
the change that caused it."""

from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.db import new_id
from app.models import Notification, User
from app.schemas.applications import NotificationOut
from app.schemas.base import to_ms


def notify(db: Session, user_id: str, type_: str, title: str, body: str = "", link: str = "") -> None:
    db.add(Notification(id=new_id("ntf"), user_id=user_id, type=type_, title=title[:200], body=body, link=link))


def _out(n: Notification) -> NotificationOut:
    return NotificationOut(
        id=n.id, type=n.type, title=n.title, body=n.body, link=n.link,
        created_at=to_ms(n.created_at), read_at=to_ms(n.read_at), read=n.read_at is not None,
    )


def list_notifications(db: Session, user: User, limit: int = 50) -> list[NotificationOut]:
    rows = db.scalars(
        select(Notification).where(Notification.user_id == user.id)
        .order_by(Notification.created_at.desc(), Notification.id).limit(limit)
    ).all()
    return [_out(n) for n in rows]


def unread_count(db: Session, user: User) -> int:
    return db.scalar(
        select(func.count()).select_from(Notification)
        .where(Notification.user_id == user.id, Notification.read_at.is_(None))
    ) or 0


def mark_read(db: Session, user: User, notification_id: str) -> NotificationOut:
    n = db.get(Notification, notification_id)
    if n is None or n.user_id != user.id:  # someone else's id looks the same as a missing one
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="This notification could not be found.")
    if n.read_at is None:
        n.read_at = datetime.now(timezone.utc)
        db.commit()
    return _out(n)


def mark_all_read(db: Session, user: User) -> int:
    result = db.execute(
        update(Notification)
        .where(Notification.user_id == user.id, Notification.read_at.is_(None))
        .values(read_at=datetime.now(timezone.utc))
    )
    db.commit()
    return result.rowcount
