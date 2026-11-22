from typing import Literal

from pydantic import EmailStr, Field, field_validator

from app.models import User
from app.services.liveness import BlinkSample
from app.schemas.base import CamelModel, to_ms

Role = Literal["candidate", "employer", "admin"]
SignupRole = Literal["candidate", "employer"]

MAX_FEATURES = 2048  # landmark templates hold 276 numbers; legacy pixel templates 576


class LandmarkTemplate(CamelModel):
    v: Literal[2]
    method: str = "landmarks"
    features: list[float] = Field(min_length=1, max_length=MAX_FEATURES)


class _EmailModel(CamelModel):
    email: EmailStr

    @field_validator("email", mode="before")
    @classmethod
    def normalise_email(cls, v):
        return v.strip().lower() if isinstance(v, str) else v


class LoginRequest(_EmailModel):
    """Sign-in step 1. A correct password only opens the face step."""

    role: Role
    password: str = Field(max_length=128)


class SignupRequest(_EmailModel):
    role: SignupRole
    name: str = Field(max_length=120)
    company: str | None = Field(default=None, max_length=160)
    password: str = Field(max_length=128)
    data_consent: bool = False


class Liveness(CamelModel):
    """The browser's blink evidence: the eye-blink score of each frame it checked. The server
    re-checks the series (app/services/liveness.py); a bare "blinked: true" is not accepted."""

    samples: list[BlinkSample] = Field(max_length=300)


class FaceEnrolRequest(CamelModel):
    template: LandmarkTemplate


class FaceVerifyRequest(CamelModel):
    template: LandmarkTemplate
    liveness: Liveness


class PendingResponse(CamelModel):
    """Result of the password step (and of sign-up): a 5-minute token that only opens the face step."""

    pending_token: str
    face_enrolled: bool
    expires_in: int  # seconds


class FaceOut(CamelModel):
    """Whether a face is enrolled. The template itself is never sent back to the browser."""

    enrolled: bool = True
    enrolled_at: int | None


class LastLogin(CamelModel):
    at: int
    method: str


class UserOut(CamelModel):
    id: str
    role: Role
    name: str
    email: str
    company: str | None = None
    created_at: int
    face: FaceOut | None = None
    last_login: LastLogin | None = None

    @classmethod
    def from_user(cls, user: User) -> "UserOut":
        return cls(
            id=user.id,
            role=user.role,
            name=user.name,
            email=user.email,
            company=user.company,
            created_at=to_ms(user.created_at),
            face=(
                FaceOut(enrolled=True, enrolled_at=to_ms(user.face_enrolled_at))
                if user.face_template is not None
                else None
            ),
            last_login=(
                LastLogin(at=to_ms(user.last_login_at), method=user.last_login_method or "password")
                if user.last_login_at
                else None
            ),
        )


class AuthResponse(CamelModel):
    token: str
    user: UserOut
