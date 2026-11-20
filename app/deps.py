from collections.abc import Callable, Iterator
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import User
from app.services.face import is_landmark_template
from app.services.security import SCOPE_FACE_PENDING, SCOPE_FULL, decode_access_token

_bearer = HTTPBearer(auto_error=False)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


DbSession = Annotated[Session, Depends(get_db)]


def _unauthorized(detail: str = "Your session has expired. Please sign in again.") -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, detail=detail, headers={"WWW-Authenticate": "Bearer"})


def _user_for_scope(db: Session, credentials: HTTPAuthorizationCredentials | None, scope: str) -> User:
    if credentials is None:
        raise _unauthorized()
    payload = decode_access_token(credentials.credentials)
    if not payload or not payload.get("sub"):
        raise _unauthorized()
    if payload.get("scope") != scope:
        # A face-pending token on a normal endpoint, or a full token on a face-step endpoint.
        raise _unauthorized(
            "Face verification is required to finish signing in."
            if payload.get("scope") == SCOPE_FACE_PENDING
            else "Your session has expired. Please sign in again."
        )
    user = db.get(User, payload["sub"])
    if user is None:
        raise _unauthorized()
    return user


def get_current_user(
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    """Full tokens only, and only for an account that has a face enrolled: after an admin resets
    someone's face, their open sessions stop working until they enrol again at the next sign-in."""
    user = _user_for_scope(db, credentials, SCOPE_FULL)
    if not is_landmark_template(user.face_template):
        raise _unauthorized("Face verification is required. Please sign in again.")
    return user


def get_face_pending_user(
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    """The user behind a face-pending token. Used by the face enrol/verify endpoints only."""
    return _user_for_scope(db, credentials, SCOPE_FACE_PENDING)


CurrentUser = Annotated[User, Depends(get_current_user)]
FacePendingUser = Annotated[User, Depends(get_face_pending_user)]


def require_role(*roles: str) -> Callable[[User], User]:
    """Dependency factory: `user: User = Depends(require_role("employer", "admin"))`."""

    def checker(user: CurrentUser) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="You don't have permission to do that.")
        return user

    return checker
