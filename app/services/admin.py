"""Admin configuration: create, edit and delete the data the rest of the app reads.

Nothing here (or anywhere else) caches configuration: the interview engine, CV matching and
evaluation load it from the database on every request, so a committed change applies to the
very next request."""

import re

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.db import new_id
from app.models import (
    Application,
    Domain,
    EvaluationCriterion,
    InterviewSession,
    Job,
    JobRole,
    JobSkill,
    QuestionTemplate,
    RoleSkill,
    ScoringRules,
    Skill,
    User,
)
from app.schemas.admin import (
    AdminStatsOut,
    AdminUserOut,
    CriteriaIn,
    CriterionOut,
    DomainIn,
    DomainOut,
    QuestionIn,
    QuestionOut,
    RoleIn,
    RoleOut,
    RulesIn,
    RulesOut,
    SkillIn,
    SkillOut,
)
from app.schemas.base import to_ms
from app.schemas.jobs import WeightedSkill
from app.services.catalog import load_rules, weighted_skills
from app.services.face import DEFAULT_FACE_THRESHOLD, is_landmark_template

RULE_DEFAULTS = {
    "weakThreshold": 60, "weakMinSessions": 2, "followUpBelow": 55, "defaultQuestions": 5,
    "faceThreshold": DEFAULT_FACE_THRESHOLD,
}


def _error(code: int, detail: str) -> HTTPException:
    return HTTPException(code, detail=detail)


def _names(items, limit: int = 3) -> str:
    items = sorted(items)
    more = f" and {len(items) - limit} more" if len(items) > limit else ""
    return ", ".join(f'"{i}"' for i in items[:limit]) + more


def _same_name(db: Session, model, name: str, exclude_id: str | None = None) -> bool:
    query = select(model.id).where(func.lower(model.name) == name.lower())
    if exclude_id:
        query = query.where(model.id != exclude_id)
    return db.scalars(query).first() is not None


# ---------- domains ----------

def _get_domain(db: Session, domain_id: str) -> Domain:
    domain = db.get(Domain, domain_id)
    if domain is None:
        raise _error(status.HTTP_404_NOT_FOUND, "This domain could not be found.")
    return domain


def list_domains(db: Session) -> list[DomainOut]:
    return [DomainOut(id=d.id, name=d.name) for d in db.scalars(select(Domain).order_by(Domain.name))]


def create_domain(db: Session, body: DomainIn) -> DomainOut:
    if _same_name(db, Domain, body.name):
        raise _error(status.HTTP_409_CONFLICT, f'A domain named "{body.name}" already exists.')
    domain = Domain(id=new_id("dom"), name=body.name)
    db.add(domain)
    db.commit()
    return DomainOut(id=domain.id, name=domain.name)


def update_domain(db: Session, domain_id: str, body: DomainIn) -> DomainOut:
    domain = _get_domain(db, domain_id)
    if _same_name(db, Domain, body.name, domain_id):
        raise _error(status.HTTP_409_CONFLICT, f'A domain named "{body.name}" already exists.')
    domain.name = body.name
    db.commit()
    return DomainOut(id=domain.id, name=domain.name)


def delete_domain(db: Session, domain_id: str) -> None:
    domain = _get_domain(db, domain_id)
    titles = db.scalars(select(JobRole.title).where(JobRole.domain_id == domain_id)).all()
    if titles:
        raise _error(
            status.HTTP_409_CONFLICT,
            f"Domain is used by a role ({_names(titles)}). Move or delete those roles first.",
        )
    db.delete(domain)
    db.commit()


# ---------- skills ----------

def _skill_out(skill: Skill) -> SkillOut:
    return SkillOut(id=skill.id, name=skill.name, aliases=skill.aliases or [], related=skill.related or [], tip=skill.tip)


def _get_skill(db: Session, skill_id: str) -> Skill:
    skill = db.get(Skill, skill_id)
    if skill is None:
        raise _error(status.HTTP_404_NOT_FOUND, "This skill could not be found.")
    return skill


def _check_related(db: Session, body: SkillIn) -> None:
    if body.name.lower() in {r.lower() for r in body.related}:
        raise _error(422, "A skill can't be related to itself.")
    known = set(db.scalars(select(Skill.name)))
    unknown = [r for r in body.related if r not in known]
    if unknown:
        raise _error(422, f"These related skills aren't in the skill library: {', '.join(unknown)}.")


def _skill_id_for(db: Session, name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:30] or "skill"
    return base if db.get(Skill, base) is None else new_id("skill")


def list_skills(db: Session) -> list[SkillOut]:
    return [_skill_out(s) for s in db.scalars(select(Skill).order_by(Skill.name))]


def create_skill(db: Session, body: SkillIn) -> SkillOut:
    if _same_name(db, Skill, body.name):
        raise _error(status.HTTP_409_CONFLICT, f'A skill named "{body.name}" already exists.')
    _check_related(db, body)
    skill = Skill(id=_skill_id_for(db, body.name), name=body.name, aliases=body.aliases, related=body.related, tip=body.tip)
    db.add(skill)
    db.commit()
    return _skill_out(skill)


def update_skill(db: Session, skill_id: str, body: SkillIn) -> SkillOut:
    skill = _get_skill(db, skill_id)
    if _same_name(db, Skill, body.name, skill_id):
        raise _error(status.HTTP_409_CONFLICT, f'A skill named "{body.name}" already exists.')
    _check_related(db, body)
    old_name = skill.name
    skill.name, skill.aliases, skill.related, skill.tip = body.name, body.aliases, body.related, body.tip
    if old_name != body.name:
        # `related` lists refer to skills by name: keep them pointing at this one.
        for other in db.scalars(select(Skill).where(Skill.id != skill_id)):
            if old_name in (other.related or []):
                other.related = [body.name if r == old_name else r for r in other.related]
    db.commit()
    return _skill_out(skill)


def delete_skill(db: Session, skill_id: str) -> None:
    skill = _get_skill(db, skill_id)
    roles = db.scalars(select(JobRole.title).join(RoleSkill).where(RoleSkill.skill_id == skill_id)).all()
    if roles:
        raise _error(
            status.HTTP_409_CONFLICT,
            f"Skill is used by a role ({_names(roles)}). Remove it from the role first.",
        )
    jobs = db.scalars(select(Job.title).join(JobSkill).where(JobSkill.skill_id == skill_id)).all()
    if jobs:
        raise _error(
            status.HTTP_409_CONFLICT,
            f"Skill is used by a job ({_names(jobs)}). Remove it from the job first.",
        )
    for other in db.scalars(select(Skill).where(Skill.id != skill_id)):
        if skill.name in (other.related or []):
            other.related = [r for r in other.related if r != skill.name]
    db.delete(skill)  # its question templates go with it (ON DELETE CASCADE)
    db.commit()


# ---------- roles ----------

def _role_out(role: JobRole) -> RoleOut:
    return RoleOut(
        id=role.id, title=role.title, domain_id=role.domain_id,
        skills=[WeightedSkill(**s) for s in weighted_skills(role.skills)],
        responsibilities=role.responsibilities or [], active=role.active,
    )


def _load_role(db: Session, role_id: str) -> JobRole:
    role = db.scalars(
        select(JobRole).where(JobRole.id == role_id).options(selectinload(JobRole.skills).selectinload(RoleSkill.skill))
    ).first()
    if role is None:
        raise _error(status.HTTP_404_NOT_FOUND, "This job role could not be found.")
    return role


def _same_title(db: Session, title: str, exclude_id: str | None = None) -> bool:
    query = select(JobRole.id).where(func.lower(JobRole.title) == title.lower())
    if exclude_id:
        query = query.where(JobRole.id != exclude_id)
    return db.scalars(query).first() is not None


def _apply_role(db: Session, role: JobRole, body: RoleIn) -> None:
    if db.get(Domain, body.domain_id) is None:
        raise _error(422, "Choose a domain from the list.")
    names = [s.name for s in body.skills]
    if len(set(names)) != len(names):
        raise _error(422, "Each skill can only be listed once.")
    skill_ids = {s.name: s.id for s in db.scalars(select(Skill).where(Skill.name.in_(names)))}
    unknown = [n for n in names if n not in skill_ids]
    if unknown:
        raise _error(422, f"These skills aren't in the skill library: {', '.join(unknown)}.")
    role.title, role.domain_id = body.title, body.domain_id
    role.responsibilities = body.responsibilities
    if body.active is not None:
        role.active = body.active
    elif role.active is None:
        role.active = True
    wanted = {skill_ids[s.name]: s.weight for s in body.skills}
    for link in list(role.skills):
        if link.skill_id in wanted:
            link.weight = wanted.pop(link.skill_id)
        else:
            role.skills.remove(link)
    for skill_id, weight in wanted.items():
        role.skills.append(RoleSkill(skill_id=skill_id, weight=weight))


def list_roles(db: Session) -> list[RoleOut]:
    roles = db.scalars(
        select(JobRole).options(selectinload(JobRole.skills).selectinload(RoleSkill.skill)).order_by(JobRole.title)
    )
    return [_role_out(r) for r in roles]


def create_role(db: Session, body: RoleIn) -> RoleOut:
    if _same_title(db, body.title):
        raise _error(status.HTTP_409_CONFLICT, f'A job role titled "{body.title}" already exists.')
    role = JobRole(id=new_id("role"))
    _apply_role(db, role, body)
    db.add(role)
    db.commit()
    db.expire_all()
    return _role_out(_load_role(db, role.id))


def update_role(db: Session, role_id: str, body: RoleIn) -> RoleOut:
    role = _load_role(db, role_id)
    if _same_title(db, body.title, role_id):
        raise _error(status.HTTP_409_CONFLICT, f'A job role titled "{body.title}" already exists.')
    _apply_role(db, role, body)
    db.commit()
    db.expire_all()
    return _role_out(_load_role(db, role_id))


def delete_role(db: Session, role_id: str) -> None:
    role = _load_role(db, role_id)
    jobs = db.scalars(select(Job.title).where(Job.role_id == role_id)).all()
    if jobs:
        raise _error(
            status.HTTP_409_CONFLICT,
            f"Role is used by a job ({_names(jobs)}). Change or delete those jobs first.",
        )
    db.delete(role)  # past sessions and candidates' target role are kept (SET NULL)
    db.commit()


# ---------- question templates ----------

def _question_out(q: QuestionTemplate) -> QuestionOut:
    return QuestionOut(
        id=q.id, skill=q.skill.name, type=q.type, text=q.text, keywords=q.keywords or [], follow_up=q.follow_up
    )


def _get_question(db: Session, question_id: str) -> QuestionTemplate:
    q = db.scalars(
        select(QuestionTemplate).where(QuestionTemplate.id == question_id).options(selectinload(QuestionTemplate.skill))
    ).first()
    if q is None:
        raise _error(status.HTTP_404_NOT_FOUND, "This question template could not be found.")
    return q


def _skill_by_name(db: Session, name: str) -> Skill:
    skill = db.scalars(select(Skill).where(Skill.name == name)).first()
    if skill is None:
        raise _error(422, f'"{name}" isn\'t in the skill library.')
    return skill


def _duplicate_question(db: Session, skill_id: str, text: str, exclude_id: str | None = None) -> bool:
    query = select(QuestionTemplate.id).where(
        QuestionTemplate.skill_id == skill_id, func.lower(QuestionTemplate.text) == text.lower()
    )
    if exclude_id:
        query = query.where(QuestionTemplate.id != exclude_id)
    return db.scalars(query).first() is not None


def list_questions(db: Session, skill: str | None = None) -> list[QuestionOut]:
    query = select(QuestionTemplate).options(selectinload(QuestionTemplate.skill)).order_by(QuestionTemplate.id)
    if skill:
        query = query.join(Skill).where(Skill.name == skill)
    return [_question_out(q) for q in db.scalars(query)]


def create_question(db: Session, body: QuestionIn) -> QuestionOut:
    skill = _skill_by_name(db, body.skill)
    if _duplicate_question(db, skill.id, body.text):
        raise _error(status.HTTP_409_CONFLICT, f"{skill.name} already has this question.")
    q = QuestionTemplate(
        id=new_id("q"), skill_id=skill.id, type=body.type, text=body.text,
        keywords=body.keywords, follow_up=body.follow_up, source="admin",
    )
    db.add(q)
    db.commit()
    return _question_out(_get_question(db, q.id))


def update_question(db: Session, question_id: str, body: QuestionIn) -> QuestionOut:
    q = _get_question(db, question_id)
    skill = _skill_by_name(db, body.skill)
    if _duplicate_question(db, skill.id, body.text, question_id):
        raise _error(status.HTTP_409_CONFLICT, f"{skill.name} already has this question.")
    q.skill_id, q.type, q.text, q.keywords, q.follow_up = skill.id, body.type, body.text, body.keywords, body.follow_up
    db.commit()
    db.expire_all()
    return _question_out(_get_question(db, question_id))


def delete_question(db: Session, question_id: str) -> None:
    db.delete(_get_question(db, question_id))  # answers already given keep their text (SET NULL)
    db.commit()


# ---------- evaluation criteria ----------

def _criteria(db: Session) -> list[EvaluationCriterion]:
    return list(db.scalars(select(EvaluationCriterion).order_by(EvaluationCriterion.created_at, EvaluationCriterion.key)))


def _criterion_out(c: EvaluationCriterion) -> CriterionOut:
    return CriterionOut(key=c.key, label=c.label, weight=c.weight, applies_to=c.applies_to, enabled=c.enabled)


def list_criteria(db: Session) -> list[CriterionOut]:
    return [_criterion_out(c) for c in _criteria(db)]


def update_criteria(db: Session, body: CriteriaIn) -> list[CriterionOut]:
    rows = {c.key: c for c in _criteria(db)}
    keys = [c.key for c in body.criteria]
    if len(set(keys)) != len(keys):
        raise _error(422, "Each criterion can only be listed once.")
    missing = [k for k in keys if k not in rows]
    if missing:
        raise _error(status.HTTP_404_NOT_FOUND, f"Unknown criteria: {', '.join(missing)}.")
    for item in body.criteria:
        rows[item.key].weight, rows[item.key].enabled = item.weight, item.enabled
    if not any(c.enabled for c in rows.values()):
        db.rollback()
        raise _error(422, "Keep at least one evaluation criterion enabled.")
    db.commit()
    return [_criterion_out(c) for c in _criteria(db)]


# ---------- scoring rules ----------

def _rules_out(db: Session) -> RulesOut:
    stored = load_rules(db)
    return RulesOut.model_validate({k: stored.get(k, default) for k, default in RULE_DEFAULTS.items()})


def get_rules(db: Session) -> RulesOut:
    return _rules_out(db)


def update_rules(db: Session, body: RulesIn) -> RulesOut:
    row = db.get(ScoringRules, 1)
    if row is None:
        row = ScoringRules(id=1, data={})
        db.add(row)
    # Assign a new dict (JSON columns don't track in-place changes). Keys that are no longer
    # used, like the old suitability weights, are dropped.
    current = {**RULE_DEFAULTS, **(row.data or {})}
    changes = body.model_dump(by_alias=True, exclude_none=True)
    row.data = {k: changes.get(k, current[k]) for k in RULE_DEFAULTS}
    db.commit()
    return _rules_out(db)


# ---------- users & stats ----------

def list_users(db: Session, role: str | None = None) -> list[AdminUserOut]:
    sessions = dict(db.execute(
        select(InterviewSession.candidate_id, func.count())
        .where(InterviewSession.status == "completed")
        .group_by(InterviewSession.candidate_id)
    ).all())
    jobs = dict(db.execute(select(Job.employer_id, func.count()).group_by(Job.employer_id)).all())
    query = select(User).order_by(User.created_at)
    if role:
        query = query.where(User.role == role)
    return [
        AdminUserOut(
            id=u.id, name=u.name, email=u.email, role=u.role, company=u.company,
            face_enrolled=is_landmark_template(u.face_template), created_at=to_ms(u.created_at),
            sessions=sessions.get(u.id, 0), jobs=jobs.get(u.id, 0),
        )
        for u in db.scalars(query)
    ]


def reset_face(db: Session, user_id: str) -> AdminUserOut:
    """Clears the user's face template: open sessions stop working and they enrol again at the next sign-in."""
    user = db.get(User, user_id)
    if user is None:
        raise _error(status.HTTP_404_NOT_FOUND, "This user could not be found.")
    user.face_template = None
    user.face_enrolled_at = None
    user.failed_face_attempts = 0
    db.commit()
    sessions = db.scalar(
        select(func.count()).select_from(InterviewSession)
        .where(InterviewSession.candidate_id == user.id, InterviewSession.status == "completed")
    ) or 0
    jobs = db.scalar(select(func.count()).select_from(Job).where(Job.employer_id == user.id)) or 0
    return AdminUserOut(
        id=user.id, name=user.name, email=user.email, role=user.role, company=user.company,
        face_enrolled=False, created_at=to_ms(user.created_at), sessions=sessions, jobs=jobs,
    )


def stats(db: Session) -> AdminStatsOut:
    def count(model, *where) -> int:
        return db.scalar(select(func.count()).select_from(model).where(*where)) or 0

    return AdminStatsOut(
        candidates=count(User, User.role == "candidate"), employers=count(User, User.role == "employer"),
        admins=count(User, User.role == "admin"),
        sessions=count(InterviewSession, InterviewSession.status == "completed"),
        jobs=count(Job), open_jobs=count(Job, Job.status == "open"), applications=count(Application),
        domains=count(Domain), roles=count(JobRole), skills=count(Skill), questions=count(QuestionTemplate),
        criteria_enabled=count(EvaluationCriterion, EvaluationCriterion.enabled.is_(True)),
    )
