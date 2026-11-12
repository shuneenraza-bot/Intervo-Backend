from fastapi import APIRouter, status

from app.deps import CurrentUser, DbSession
from app.schemas.auth import (
    AuthResponse,
    FaceEnrolRequest,
    LoginRequest,
    LookupRequest,
    LookupResponse,
    SignupRequest,
    UserOut,
)
from app.services import auth as auth_service
from app.services.face import is_landmark_template
from app.services.security import create_access_token

router = APIRouter(prefix="/auth", tags=["auth"])


def _auth_response(user) -> AuthResponse:
    return AuthResponse(token=create_access_token(user.id, user.role), user=UserOut.from_user(user))


@router.post("/lookup", response_model=LookupResponse)
def lookup(body: LookupRequest, db: DbSession):
    """Sign-in step 1: does this email + role exist, and should the UI offer Face ID?"""
    user = auth_service.find_account(db, body.email, body.role)
    return LookupResponse(face_enabled=is_landmark_template(user.face_template))


@router.post("/signup", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def signup(body: SignupRequest, db: DbSession):
    return _auth_response(auth_service.signup(db, body))


@router.post("/login", response_model=AuthResponse)
def login(body: LoginRequest, db: DbSession):
    """Sign in with a password OR a face template; either one is enough."""
    return _auth_response(auth_service.login(db, body))


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser):
    return UserOut.from_user(user)


@router.put("/face", response_model=UserOut)
def enrol_face(body: FaceEnrolRequest, user: CurrentUser, db: DbSession):
    """Enrol or replace the signed-in user's Face ID template."""
    return UserOut.from_user(auth_service.enrol_face(db, user, body.template))


@router.delete("/face", response_model=UserOut)
def delete_face(user: CurrentUser, db: DbSession):
    return UserOut.from_user(auth_service.remove_face(db, user))
