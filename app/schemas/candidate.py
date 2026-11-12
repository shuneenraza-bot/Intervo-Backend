"""Bodies for the candidate sync endpoints: PUT /profile and POST /sessions."""

import json
from typing import Any, Literal

from pydantic import Field, field_validator

from app.schemas.base import CamelModel

MAX_INDICATORS_JSON = 4000  # characters; video cues are a handful of numbers


class EducationIn(CamelModel):
    degree: str = Field(default="", max_length=200)
    institution: str = Field(default="", max_length=200)


class ProjectIn(CamelModel):
    name: str = Field(default="", max_length=200)


class CVSummaryIn(CamelModel):
    """The CV facts an employer may see. Contact details and CV text are never sent."""

    education: list[EducationIn] = Field(default_factory=list, max_length=20)
    experience_years: float = Field(default=0, ge=0, le=80)
    projects: list[ProjectIn] = Field(default_factory=list, max_length=50)


class ProfileIn(CamelModel):
    """Replaces the candidate's skills, CV summary and sharing switch."""

    skills: list[str] = Field(default_factory=list, max_length=200)
    cv: CVSummaryIn | None = None
    share_with_employers: bool

    @field_validator("skills")
    @classmethod
    def clean_skills(cls, names: list[str]) -> list[str]:
        cleaned = [n.strip() for n in names]
        if any(len(n) > 120 for n in cleaned):
            raise ValueError("Skill names can be at most 120 characters.")
        return list(dict.fromkeys(n for n in cleaned if n))  # drop blanks and duplicates, keep order


class ProfileOut(CamelModel):
    skills: list[str]
    cv: CVSummaryIn | None
    share_with_employers: bool


class AnswerIn(CamelModel):
    """One scored answer. The answer text itself is not accepted or stored."""

    question_id: str | None = Field(default=None, max_length=80)
    question: str = Field(default="", max_length=2000)
    skill: str = Field(min_length=1, max_length=120)
    type: Literal["technical", "behavioral"]
    score: int = Field(ge=0, le=100)
    criteria: dict[str, int | float] = Field(default_factory=dict)
    indicators: dict[str, Any] | None = None
    reason: str | None = Field(default=None, max_length=20)

    @field_validator("criteria")
    @classmethod
    def criteria_in_range(cls, criteria: dict) -> dict:
        if len(criteria) > 30 or any(len(k) > 40 or not 0 <= v <= 100 for k, v in criteria.items()):
            raise ValueError("Criteria scores must be between 0 and 100.")
        return criteria

    @field_validator("indicators")
    @classmethod
    def indicators_small(cls, indicators: dict | None) -> dict | None:
        if indicators is not None and len(json.dumps(indicators)) > MAX_INDICATORS_JSON:
            raise ValueError("Indicators are too large.")
        return indicators


class SessionIn(CamelModel):
    """A finished practice session. `id` is the id the browser already uses for it, which
    makes re-sending the same session safe; the server makes one up if it's missing."""

    id: str | None = Field(default=None, min_length=1, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")
    role_id: str | None = Field(default=None, max_length=80)
    mode: Literal["text", "voice", "video"] = "text"
    date: int | None = Field(default=None, ge=0, le=4_102_444_800_000)  # Unix ms, up to 2100
    score: int = Field(ge=0, le=100)
    answers: list[AnswerIn] = Field(min_length=1, max_length=100)
