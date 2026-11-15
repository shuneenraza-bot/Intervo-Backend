"""CV / job-description shapes.

Two families:
  * LLM* models (snake_case) validate what a provider returns (Gemini or the rules engine).
  * The CamelModel ones are the API shapes the frontend already uses (ParsedCV in API.md).
"""

from pydantic import BaseModel, Field, field_validator

from app.schemas.base import CamelModel


def _trim(items: list[str], limit: int, size: int) -> list[str]:
    seen: dict[str, None] = {}
    for item in items:
        item = str(item).strip()[:size]
        if item:
            seen.setdefault(item, None)
    return list(seen)[:limit]


# ---------- provider output (validated before anything is trusted) ----------

class LLMEducation(BaseModel):
    degree: str = ""
    institution: str = ""
    dates: str = ""
    score: str = ""


class LLMExperience(BaseModel):
    title: str = ""
    company: str = ""
    dates: str = ""
    details: str = ""
    months: int | None = None


class LLMProject(BaseModel):
    name: str = ""
    details: str = ""
    tech: list[str] = Field(default_factory=list)


class LLMCV(BaseModel):
    summary: str = ""
    skills: list[str] = Field(default_factory=list)
    other_skills: list[str] = Field(default_factory=list)
    education: list[LLMEducation] = Field(default_factory=list)
    experience: list[LLMExperience] = Field(default_factory=list)
    projects: list[LLMProject] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)


class LLMJDSkill(BaseModel):
    name: str
    weight: int = 2


class LLMJD(BaseModel):
    title: str = ""
    skills: list[LLMJDSkill] = Field(default_factory=list)
    min_years: int = 0
    education: str = ""
    fresher_friendly: bool = False


# ---------- API shapes ----------

class ContactModel(CamelModel):
    name: str = Field(default="", max_length=200)
    email: str = Field(default="", max_length=255)
    phone: str = Field(default="", max_length=60)
    linkedin: str = Field(default="", max_length=200)
    github: str = Field(default="", max_length=200)
    location: str = Field(default="", max_length=200)


class EducationModel(CamelModel):
    degree: str = Field(default="", max_length=200)
    institution: str = Field(default="", max_length=200)
    dates: str = Field(default="", max_length=80)
    score: str = Field(default="", max_length=60)


class ExperienceModel(CamelModel):
    title: str = Field(default="", max_length=200)
    company: str = Field(default="", max_length=200)
    dates: str = Field(default="", max_length=80)
    details: str = Field(default="", max_length=4000)
    months: int | None = Field(default=None, ge=0, le=1200)


class ProjectModel(CamelModel):
    name: str = Field(default="", max_length=200)
    details: str = Field(default="", max_length=4000)
    tech: list[str] = Field(default_factory=list, max_length=50)


class ParsedCV(CamelModel):
    contact: ContactModel = Field(default_factory=ContactModel)
    summary: str = Field(default="", max_length=2000)
    skills: list[str] = Field(default_factory=list, max_length=200)
    other_skills: list[str] = Field(default_factory=list, max_length=100)
    education: list[EducationModel] = Field(default_factory=list, max_length=20)
    experience: list[ExperienceModel] = Field(default_factory=list, max_length=30)
    projects: list[ProjectModel] = Field(default_factory=list, max_length=50)
    certifications: list[str] = Field(default_factory=list, max_length=50)
    experience_years: float = Field(default=0, ge=0, le=80)
    sections_found: list[str] = Field(default_factory=list, max_length=20)
    warnings: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("skills", "other_skills", "certifications")
    @classmethod
    def clean_lists(cls, items: list[str]) -> list[str]:
        return _trim(items, 200, 200)


class CVResponse(CamelModel):
    cv: ParsedCV
    provider: str | None = None  # "gemini" or "rules"
    file_name: str | None = None
    text: str = ""


class JDSkill(CamelModel):
    name: str = Field(min_length=1, max_length=120)
    weight: int = Field(default=2, ge=1, le=3)


class JDParseIn(CamelModel):
    text: str = Field(min_length=1, max_length=20000)
    role_skills: list[JDSkill] = Field(default_factory=list, max_length=100)


class ParsedJD(CamelModel):
    title: str = Field(default="", max_length=200)
    skills: list[JDSkill] = Field(default_factory=list, max_length=100)
    min_years: int = Field(default=0, ge=0, le=60)
    education: str = Field(default="", max_length=200)
    fresher_friendly: bool = False


class JDParseOut(ParsedJD):
    provider: str


class MatchIn(CamelModel):
    """Either a role id (its configured skills and weights) or a parsed JD."""

    role_id: str | None = Field(default=None, max_length=80)
    jd: ParsedJD | None = None


class PartialSkill(JDSkill):
    via: str


class RequirementCheck(CamelModel):
    key: str
    label: str
    required: str
    actual: str
    met: bool


class MatchOut(CamelModel):
    matched: list[JDSkill]
    partial: list[PartialSkill]
    missing: list[JDSkill]
    percentage: int
    checks: list[RequirementCheck]
