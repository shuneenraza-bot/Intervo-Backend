"""Request bodies for the interview endpoints, and the shapes the AI must return."""

import math
import re
from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, Field, field_validator

from app.schemas.base import CamelModel

MAX_ANSWER_CHARS = 8000
MAX_INDICATORS_JSON = 4000
INDICATOR_KEYS = ("lighting", "framing", "steadiness", "eyeContact", "expressiveness")  # video cues, 0-100


# ---------- requests ----------

class StartIn(CamelModel):
    role_id: str | None = Field(default=None, max_length=80)
    job_id: str | None = Field(default=None, max_length=80)
    mode: Literal["text", "voice", "video"] = "text"
    count: int | None = Field(default=None, ge=1, le=10)  # default: scoring_rules.defaultQuestions


def validate_indicators(v: dict | None) -> dict | None:
    import json

    if v is None:
        return v
    if len(json.dumps(v)) > MAX_INDICATORS_JSON:
        raise ValueError("Indicators are too large.")
    for k in INDICATOR_KEYS:
        if k in v and (isinstance(v[k], bool) or not isinstance(v[k], (int, float)) or not 0 <= v[k] <= 100):
            raise ValueError(f"Indicator {k} must be a number from 0 to 100.")
    return v


class _TextBody(CamelModel):
    answer: str = Field(max_length=MAX_ANSWER_CHARS)
    indicators: dict[str, Any] | None = None

    @field_validator("answer")
    @classmethod
    def not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Write or say your answer first.")
        return v

    @field_validator("indicators")
    @classmethod
    def indicators_ok(cls, v: dict | None) -> dict | None:
        return validate_indicators(v)


class AnswerBody(_TextBody):
    source: Literal["text", "voice", "video"] | None = None  # default: video if indicators are sent, else text
    question_id: str = Field(min_length=1, max_length=80)  # the question's `id` from the start response


class FollowUpBody(_TextBody):
    pass


# ---------- what the AI returns (validated, then clamped in Python) ----------

def _score(v: Any) -> int:
    """Any number the model sends becomes an int between 0 and 100. Anything else is invalid."""
    if isinstance(v, bool) or not isinstance(v, (int, float)) or (isinstance(v, float) and math.isnan(v)):
        raise ValueError("score must be a number")
    return int(min(100, max(0, math.floor(v + 0.5))))


Score = Annotated[int, BeforeValidator(_score)]


class LLMEvaluation(BaseModel):
    # Every criterion is optional so a model that omits one is detected and handled by the caller
    # (retry, then fill from the rules evaluator) instead of failing validation.
    technical: Score | None = None
    relevance: Score | None = None
    completeness: Score | None = None
    clarity: Score | None = None
    communication: Score | None = None
    star: Score | None = None
    tips: list[str] = Field(default_factory=list)
    needs_follow_up: bool = False

    @field_validator("tips", mode="before")
    @classmethod
    def clean_tips(cls, tips: Any) -> list[str]:
        if not isinstance(tips, list):
            return []
        return [t.strip()[:220] for t in tips if isinstance(t, str) and t.strip()][:3]


MAX_QUESTION_WORDS = 59  # "under 60 words"
# Asking the candidate to write, run or trace code.
CODING = re.compile(
    r"\b(write|code|type out|compose)\b[^.?!]{0,40}\b(code|function|program|script|query|snippet|method|class)\b"
    r"|\bimplement (a |an |the )?(function|method|class|program|algorithm)\b"
    r"|\boutput of\b|\bcode snippet\b|\b(following|this|below) code\b|\brun (this|the following)\b|\bleetcode\b|```",
    re.I,
)


class LLMGeneratedQuestion(BaseModel):
    """A new interview question. Output that breaks these rules is not used; the checks that need
    the database (right skill, not a repeat) are in app/services/question_gen.py."""

    skill: str = Field(min_length=1, max_length=120)
    text: str = Field(min_length=15, max_length=600)
    keywords: list[str]
    follow_up: str = Field(min_length=10, max_length=400)

    @field_validator("text", "follow_up")
    @classmethod
    def short_and_no_coding(cls, v: str) -> str:
        v = " ".join(v.split())
        if len(v.split()) > MAX_QUESTION_WORDS:
            raise ValueError("a question must be under 60 words")
        if CODING.search(v):
            raise ValueError("no coding or code-execution questions")
        return v

    @field_validator("keywords", mode="before")
    @classmethod
    def four_to_six_key_points(cls, v: Any) -> list[str]:
        if not isinstance(v, list):
            raise ValueError("keywords must be a list")
        points = list(dict.fromkeys(" ".join(k.split()).lower()[:60] for k in v if isinstance(k, str) and k.strip()))
        if not 4 <= len(points) <= 6:
            raise ValueError("4 to 6 different key points are needed")
        return points


class LLMFollowUp(BaseModel):
    question: str = Field(min_length=10, max_length=400)
