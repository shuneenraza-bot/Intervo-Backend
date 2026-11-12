"""Admin-managed configuration: domains, skills, roles, questions, criteria, rules."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, String, Text, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, JSONType, TimestampMixin


class Domain(TimestampMixin, Base):
    __tablename__ = "domains"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)

    roles: Mapped[list[JobRole]] = relationship(back_populates="domain")


class Skill(TimestampMixin, Base):
    __tablename__ = "skills"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    aliases: Mapped[list[str]] = mapped_column(JSONType, default=list)
    related: Mapped[list[str]] = mapped_column(JSONType, default=list)  # related skill names
    tip: Mapped[str] = mapped_column(Text, default="", server_default="")


class JobRole(TimestampMixin, Base):
    __tablename__ = "job_roles"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    domain_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("domains.id", ondelete="RESTRICT"), index=True
    )
    title: Mapped[str] = mapped_column(String(160))

    domain: Mapped[Domain] = relationship(back_populates="roles")
    skills: Mapped[list[RoleSkill]] = relationship(
        back_populates="role", cascade="all, delete-orphan"
    )


class RoleSkill(TimestampMixin, Base):
    __tablename__ = "role_skills"
    __table_args__ = (CheckConstraint("weight BETWEEN 1 AND 3", name="weight"),)

    role_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("job_roles.id", ondelete="CASCADE"), primary_key=True
    )
    skill_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("skills.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    weight: Mapped[int] = mapped_column(Integer, default=2, server_default="2")

    role: Mapped[JobRole] = relationship(back_populates="skills")
    skill: Mapped[Skill] = relationship()


class QuestionTemplate(TimestampMixin, Base):
    __tablename__ = "question_templates"
    __table_args__ = (CheckConstraint("type IN ('technical', 'behavioral')", name="type"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    skill_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("skills.id", ondelete="CASCADE"), index=True
    )
    type: Mapped[str] = mapped_column(String(20), index=True)
    text: Mapped[str] = mapped_column(Text)
    keywords: Mapped[list[str]] = mapped_column(JSONType, default=list)
    follow_up: Mapped[str] = mapped_column(Text, default="", server_default="")

    skill: Mapped[Skill] = relationship()


class EvaluationCriterion(TimestampMixin, Base):
    __tablename__ = "evaluation_criteria"
    __table_args__ = (
        CheckConstraint("applies_to IN ('all', 'technical', 'behavioral')", name="applies_to"),
        CheckConstraint("weight >= 0", name="weight"),
    )

    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    label: Mapped[str] = mapped_column(String(120))
    weight: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    applies_to: Mapped[str] = mapped_column(String(20), default="all", server_default="all")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())


class ScoringRules(TimestampMixin, Base):
    """Single row (id = 1) holding the rules object, e.g. {"faceThreshold": 0.55, ...}."""

    __tablename__ = "scoring_rules"
    __table_args__ = (CheckConstraint("id = 1", name="single_row"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False, default=1)
    data: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
