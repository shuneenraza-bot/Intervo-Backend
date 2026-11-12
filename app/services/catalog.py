"""Reads the admin configuration in the shape of the frontend's `config` object (src/data.js)."""

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Domain, EvaluationCriterion, JobRole, QuestionTemplate, RoleSkill, ScoringRules, Skill


def weighted_skills(links) -> list[dict]:
    """RoleSkill / JobSkill rows -> [{"name", "weight"}], most important first."""
    return [
        {"name": link.skill.name, "weight": link.weight}
        for link in sorted(links, key=lambda link: (-link.weight, link.skill.name))
    ]


def load_rules(db: Session) -> dict:
    row = db.get(ScoringRules, 1)
    return dict(row.data) if row and row.data else {}


def load_skills(db: Session) -> list[dict]:
    return [
        {"name": s.name, "aliases": s.aliases or [], "related": s.related or [], "tip": s.tip}
        for s in db.scalars(select(Skill).order_by(Skill.name))
    ]


def load_config(db: Session) -> dict:
    roles = db.scalars(
        select(JobRole).options(selectinload(JobRole.skills).selectinload(RoleSkill.skill)).order_by(JobRole.title)
    )
    questions = db.scalars(
        select(QuestionTemplate).options(selectinload(QuestionTemplate.skill)).order_by(QuestionTemplate.id)
    )
    return {
        "domains": [{"id": d.id, "name": d.name} for d in db.scalars(select(Domain).order_by(Domain.name))],
        "skills": load_skills(db),
        "roles": [
            {"id": r.id, "title": r.title, "domainId": r.domain_id, "skills": weighted_skills(r.skills)}
            for r in roles
        ],
        "questions": [
            {"id": q.id, "skill": q.skill.name, "type": q.type, "text": q.text,
             "keywords": q.keywords or [], "followUp": q.follow_up}
            for q in questions
        ],
        "criteria": [
            {"key": c.key, "label": c.label, "weight": c.weight, "appliesTo": c.applies_to, "enabled": c.enabled}
            for c in db.scalars(select(EvaluationCriterion).order_by(EvaluationCriterion.created_at, EvaluationCriterion.key))
        ],
        "rules": load_rules(db),
    }
