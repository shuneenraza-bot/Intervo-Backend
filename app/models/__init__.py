"""Import every model here so Base.metadata (and Alembic) sees all tables."""

from app.models.catalog import (
    Domain,
    EvaluationCriterion,
    JobRole,
    QuestionTemplate,
    RoleSkill,
    ScoringRules,
    Skill,
)
from app.models.interview import InterviewSession, SessionAnswer
from app.models.job import Application, Job, JobSkill
from app.models.user import CandidateProfile, User

__all__ = [
    "Application",
    "CandidateProfile",
    "Domain",
    "EvaluationCriterion",
    "InterviewSession",
    "Job",
    "JobRole",
    "JobSkill",
    "QuestionTemplate",
    "RoleSkill",
    "ScoringRules",
    "SessionAnswer",
    "Skill",
    "User",
]
