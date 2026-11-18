"""Request/response models for the admin configuration endpoints (/api/admin/*)."""

from typing import Literal

from pydantic import Field, field_validator

from app.schemas.base import CamelModel
from app.schemas.jobs import WeightedSkill


def _clean(v: str, message: str) -> str:
    v = (v or "").strip()
    if not v:
        raise ValueError(message)
    return v


def _clean_list(values: list[str], *, lower: bool = False) -> list[str]:
    """Trim, drop blanks, drop duplicates (keeping order)."""
    out: list[str] = []
    for v in values:
        v = (v or "").strip()
        v = v.lower() if lower else v
        if v and v not in out:
            out.append(v)
    return out


class DomainIn(CamelModel):
    name: str = Field(max_length=120)

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, v: str) -> str:
        return _clean(v, "Give the domain a name.")


class DomainOut(CamelModel):
    id: str
    name: str


class RoleIn(CamelModel):
    title: str = Field(max_length=160)
    domain_id: str
    skills: list[WeightedSkill] = Field(min_length=1, max_length=50)

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, v: str) -> str:
        return _clean(v, "Give the role a title.")


class RoleOut(CamelModel):
    id: str
    title: str
    domain_id: str
    skills: list[WeightedSkill]


class SkillIn(CamelModel):
    name: str = Field(max_length=120)
    aliases: list[str] = Field(default_factory=list, max_length=50)
    related: list[str] = Field(default_factory=list, max_length=50)  # names of other skills
    tip: str = Field(default="", max_length=1000)

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, v: str) -> str:
        return _clean(v, "Give the skill a name.")

    @field_validator("aliases")
    @classmethod
    def aliases_lowercase(cls, v: list[str]) -> list[str]:
        return _clean_list(v, lower=True)  # the CV/JD extractor matches lowercase text

    @field_validator("related")
    @classmethod
    def related_clean(cls, v: list[str]) -> list[str]:
        return _clean_list(v)

    @field_validator("tip")
    @classmethod
    def tip_trim(cls, v: str) -> str:
        return v.strip()


class SkillOut(CamelModel):
    id: str
    name: str
    aliases: list[str]
    related: list[str]
    tip: str


class QuestionIn(CamelModel):
    skill: str  # skill name
    type: Literal["technical", "behavioral"]
    text: str = Field(max_length=1000)
    keywords: list[str] = Field(default_factory=list, max_length=30)
    follow_up: str = Field(default="", max_length=1000)

    @field_validator("text")
    @classmethod
    def text_long_enough(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 10:
            raise ValueError("Write the question (at least 10 characters).")
        return v

    @field_validator("keywords")
    @classmethod
    def keywords_clean(cls, v: list[str]) -> list[str]:
        return _clean_list(v, lower=True)

    @field_validator("follow_up")
    @classmethod
    def follow_up_trim(cls, v: str) -> str:
        return v.strip()


class QuestionOut(CamelModel):
    id: str
    skill: str
    type: str
    text: str
    keywords: list[str]
    follow_up: str


class CriterionIn(CamelModel):
    key: str
    weight: int = Field(ge=1, le=3)
    enabled: bool


class CriteriaIn(CamelModel):
    criteria: list[CriterionIn] = Field(min_length=1, max_length=20)


class CriterionOut(CamelModel):
    key: str
    label: str
    weight: int
    applies_to: str
    enabled: bool


class RulesIn(CamelModel):
    """Any subset of the rules; omitted ones keep their current value."""

    weak_threshold: int | None = Field(default=None, ge=30, le=90)
    weak_min_sessions: int | None = Field(default=None, ge=1, le=5)
    follow_up_below: int | None = Field(default=None, ge=30, le=80)
    default_questions: int | None = Field(default=None, ge=3, le=6)
    face_threshold: float | None = Field(default=None, ge=0.3, le=0.9)


class RulesOut(CamelModel):
    weak_threshold: int
    weak_min_sessions: int
    follow_up_below: int
    default_questions: int
    face_threshold: float


class AdminUserOut(CamelModel):
    """Account list row: never a password hash or a face template."""

    id: str
    name: str
    email: str
    role: str
    company: str | None
    face_enrolled: bool
    created_at: int
    sessions: int  # completed interview sessions (candidates)
    jobs: int  # job postings (employers)


class AdminStatsOut(CamelModel):
    candidates: int
    employers: int
    admins: int
    sessions: int
    jobs: int
    open_jobs: int
    applications: int
    domains: int
    roles: int
    skills: int
    questions: int
    criteria_enabled: int
