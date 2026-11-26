"""Admin configuration endpoints. Every route needs an admin account."""

from fastapi import APIRouter, Depends, Response, status

from app.deps import DbSession, require_role
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
from app.services import admin as svc

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_role("admin"))])


def _no_content() -> Response:
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---- domains ----

@router.get("/domains", response_model=list[DomainOut])
def list_domains(db: DbSession):
    return svc.list_domains(db)


@router.post("/domains", response_model=DomainOut, status_code=status.HTTP_201_CREATED)
def create_domain(body: DomainIn, db: DbSession):
    return svc.create_domain(db, body)


@router.put("/domains/{domain_id}", response_model=DomainOut)
def update_domain(domain_id: str, body: DomainIn, db: DbSession):
    return svc.update_domain(db, domain_id, body)


@router.delete("/domains/{domain_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_domain(domain_id: str, db: DbSession):
    svc.delete_domain(db, domain_id)
    return _no_content()


# ---- job roles ----

@router.get("/roles", response_model=list[RoleOut])
def list_roles(db: DbSession):
    return svc.list_roles(db)


@router.post("/roles", response_model=RoleOut, status_code=status.HTTP_201_CREATED)
def create_role(body: RoleIn, db: DbSession):
    return svc.create_role(db, body)


@router.put("/roles/{role_id}", response_model=RoleOut)
def update_role(role_id: str, body: RoleIn, db: DbSession):
    return svc.update_role(db, role_id, body)


@router.delete("/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_role(role_id: str, db: DbSession):
    svc.delete_role(db, role_id)
    return _no_content()


# ---- skills ----

@router.get("/skills", response_model=list[SkillOut])
def list_skills(db: DbSession):
    return svc.list_skills(db)


@router.post("/skills", response_model=SkillOut, status_code=status.HTTP_201_CREATED)
def create_skill(body: SkillIn, db: DbSession):
    return svc.create_skill(db, body)


@router.put("/skills/{skill_id}", response_model=SkillOut)
def update_skill(skill_id: str, body: SkillIn, db: DbSession):
    return svc.update_skill(db, skill_id, body)


@router.delete("/skills/{skill_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_skill(skill_id: str, db: DbSession):
    svc.delete_skill(db, skill_id)
    return _no_content()


# ---- question templates ----

@router.get("/questions", response_model=list[QuestionOut])
def list_questions(db: DbSession, skill: str | None = None):
    return svc.list_questions(db, skill)


@router.post("/questions", response_model=QuestionOut, status_code=status.HTTP_201_CREATED)
def create_question(body: QuestionIn, db: DbSession):
    return svc.create_question(db, body)


@router.put("/questions/{question_id}", response_model=QuestionOut)
def update_question(question_id: str, body: QuestionIn, db: DbSession):
    return svc.update_question(db, question_id, body)


@router.post("/questions/{question_id}/approve", response_model=QuestionOut)
def approve_question(question_id: str, db: DbSession):
    return svc.approve_question(db, question_id)


@router.delete("/questions/{question_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_question(question_id: str, db: DbSession):
    svc.delete_question(db, question_id)
    return _no_content()


# ---- evaluation criteria and scoring rules ----

@router.get("/criteria", response_model=list[CriterionOut])
def get_criteria(db: DbSession):
    return svc.list_criteria(db)


@router.put("/criteria", response_model=list[CriterionOut])
def put_criteria(body: CriteriaIn, db: DbSession):
    return svc.update_criteria(db, body)


@router.get("/rules", response_model=RulesOut)
def get_rules(db: DbSession):
    return svc.get_rules(db)


@router.put("/rules", response_model=RulesOut)
def put_rules(body: RulesIn, db: DbSession):
    return svc.update_rules(db, body)


# ---- users and overview counts ----

@router.get("/users", response_model=list[AdminUserOut])
def list_users(db: DbSession, role: str | None = None):
    return svc.list_users(db, role)


@router.post("/users/{user_id}/reset-face", response_model=AdminUserOut)
def reset_face(user_id: str, db: DbSession):
    """Clears a user's face template. They must enrol a new face at their next sign-in."""
    return svc.reset_face(db, user_id)


@router.get("/stats", response_model=AdminStatsOut)
def get_stats(db: DbSession):
    return svc.stats(db)
