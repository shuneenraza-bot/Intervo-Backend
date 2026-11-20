from typing import Annotated

from fastapi import APIRouter, Query

from app.deps import CurrentUser, DbSession
from app.schemas.applications import NotificationOut, UnreadCount
from app.services import notifications as service

router = APIRouter(tags=["notifications"])


@router.get("/notifications", response_model=list[NotificationOut])
def list_notifications(user: CurrentUser, db: DbSession, limit: Annotated[int, Query(ge=1, le=100)] = 50):
    return service.list_notifications(db, user, limit)


@router.get("/notifications/unread-count", response_model=UnreadCount)
def unread_count(user: CurrentUser, db: DbSession):
    return UnreadCount(count=service.unread_count(db, user))


@router.post("/notifications/read-all", response_model=UnreadCount)
def read_all(user: CurrentUser, db: DbSession):
    service.mark_all_read(db, user)
    return UnreadCount(count=0)


@router.post("/notifications/{notification_id}/read", response_model=NotificationOut)
def read_one(notification_id: str, user: CurrentUser, db: DbSession):
    return service.mark_read(db, user, notification_id)
