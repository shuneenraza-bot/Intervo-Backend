from fastapi import APIRouter, status

from app.deps import CurrentUser, DbSession, FacePendingUser
from app.schemas.auth import (
    AuthResponse,
    FaceEnrolRequest,
    FaceVerifyRequest,
    LoginRequest,
    PendingResponse,
    SignupRequest,
    UserOut,
)
from app.services import auth as auth_service
from app.services.face import is_landmark_template
from app.services.security import FACE_PENDING_MINUTES, SCOPE_FACE_PENDING, create_access_token

router = APIRouter(prefix="/auth", tags=["auth"])


def _pending(user) -> PendingResponse:
    return PendingResponse(
        pending_token=create_access_token(user.id, user.role, scope=SCOPE_FACE_PENDING),
        face_enrolled=is_landmark_template(user.face_template),
        expires_in=FACE_PENDING_MINUTES * 60,
    )


def _full(user) -> AuthResponse:
    return AuthResponse(token=create_access_token(user.id, user.role), user=UserOut.from_user(user))


@router.post("/signup", response_model=PendingResponse, status_code=status.HTTP_201_CREATED)
def signup(body: SignupRequest, db: DbSession):
    """Creates the account. The face step (enrol) must follow before there is a full token."""
    return _pending(auth_service.signup(db, body))


@router.post("/login", response_model=PendingResponse)
def login(body: LoginRequest, db: DbSession):
    """Step 1: email, role and password. Returns a 5-minute face-pending token, never a full token."""
    return _pending(auth_service.login(db, body))


@router.post("/face/verify", response_model=AuthResponse)
def verify_face(body: FaceVerifyRequest, user: FacePendingUser, db: DbSession):
    """Step 2 for an enrolled account (face-pending token). Success returns the full token."""
    return _full(auth_service.verify_face(db, user, body))


@router.post("/face/enroll", response_model=AuthResponse)
def enrol_face_pending(body: FaceEnrolRequest, user: FacePendingUser, db: DbSession):
    """Step 2 for an account without a face (face-pending token). Success returns the full token."""
    return _full(auth_service.enrol_face_pending(db, user, body.template))


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser):
    return UserOut.from_user(user)


@router.put("/face", response_model=UserOut)
def enrol_face(body: FaceEnrolRequest, user: CurrentUser, db: DbSession):
    """Re-enrol: replace the signed-in user's face template. There is no delete."""
    return UserOut.from_user(auth_service.enrol_face(db, user, body.template))
