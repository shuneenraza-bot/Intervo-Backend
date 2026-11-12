from typing import Literal

from pydantic import EmailStr, Field, field_validator

from app.models import User
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


class LookupRequest(_EmailModel):
    role: Role


class LookupResponse(CamelModel):
    face_enabled: bool


class LoginRequest(_EmailModel):
    role: Role
    password: str | None = Field(default=None, max_length=128)
    face_template: LandmarkTemplate | None = None


class SignupFace(CamelModel):
    # A landmark template, or a legacy pixel template (plain number array)
    template: LandmarkTemplate | list[float] = Field(union_mode="left_to_right")

    @field_validator("template")
    @classmethod
    def limit_size(cls, v):
        if isinstance(v, list) and not 1 <= len(v) <= MAX_FEATURES:
            raise ValueError("Face template has an invalid size.")
        return v


class SignupRequest(_EmailModel):
    role: SignupRole
    name: str = Field(max_length=120)
    company: str | None = Field(default=None, max_length=160)
    password: str = Field(max_length=128)
    data_consent: bool = False
    face: SignupFace | None = None


class FaceEnrolRequest(CamelModel):
    template: LandmarkTemplate


class FaceOut(CamelModel):
    template: dict | list
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
                FaceOut(template=user.face_template, enrolled_at=to_ms(user.face_enrolled_at))
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
