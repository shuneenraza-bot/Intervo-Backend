"""Jobs, applications and the employer's ranked candidate list."""

from collections import Counter
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.db import new_id
from app.models import (
    Application,
    CandidateProfile,
    InterviewSession,
    Job,
    JobRole,
    JobSkill,
    SessionAnswer,
    Skill,
    User,
)
from app.schemas.base import to_ms
from app.schemas.jobs import ApplicationOut, JobIn, JobOut, JobsResponse
from app.services.catalog import load_rules, load_skills
from app.services.suitability import cv_summary, suitability

_JOB_OPTIONS = (selectinload(Job.skills).selectinload(JobSkill.skill),)


def _error(code: int, detail: str) -> HTTPException:
    return HTTPException(code, detail=detail)


# ---------- jobs ----------

def get_job(db: Session, job_id: str) -> Job:
    job = db.scalars(select(Job).where(Job.id == job_id).options(*_JOB_OPTIONS)).first()
    if job is None:
        raise _error(status.HTTP_404_NOT_FOUND, "This job could not be found.")
    return job


def get_owned_job(db: Session, job_id: str, user: User) -> Job:
    job = get_job(db, job_id)
    if job.employer_id != user.id:
        raise _error(status.HTTP_403_FORBIDDEN, "Only the employer who posted this job can do that.")
    return job


def list_jobs(db: Session, user: User) -> JobsResponse:
    """Open jobs for everyone. Employers also get their own closed jobs, the applications
    on their jobs and an applicant count per job; candidates get their own applications."""
    query = select(Job).options(*_JOB_OPTIONS).order_by(Job.created_at.desc())
    if user.role == "employer":
        query = query.where(or_(Job.status == "open", Job.employer_id == user.id))
    elif user.role != "admin":
        query = query.where(Job.status == "open")
    jobs = db.scalars(query).all()

    if user.role == "employer":
        applications = db.scalars(
            select(Application).join(Job).where(Job.employer_id == user.id).order_by(Application.created_at)
        ).all()
    elif user.role == "candidate":
        applications = db.scalars(
            select(Application).where(Application.candidate_id == user.id).order_by(Application.created_at)
        ).all()
    else:
        applications = []

    counts = Counter(a.job_id for a in applications)
    return JobsResponse(
        jobs=[JobOut.from_job(j, counts[j.id] if j.employer_id == user.id else None) for j in jobs],
        applications=[ApplicationOut.from_application(a) for a in applications],
    )


def _apply_job_fields(db: Session, job: Job, body: JobIn) -> None:
    if db.get(JobRole, body.role_id) is None:
        raise _error(422, "Choose a job role from the list.")

    names = [s.name for s in body.skills]
    if len(set(names)) != len(names):
        raise _error(422, "Each skill can only be listed once.")
    skill_ids = {s.name: s.id for s in db.scalars(select(Skill).where(Skill.name.in_(names)))} if names else {}
    unknown = [n for n in names if n not in skill_ids]
    if unknown:
        raise _error(422, f"These skills aren't in the skill library: {', '.join(unknown)}.")

    job.title = body.title
    job.role_id = body.role_id
    job.description = body.description
    job.location = body.location
    job.mode = body.mode
    job.level = body.level
    job.type = body.type
    job.status = body.status
    job.min_score = body.success.min_score
    job.min_match = body.success.min_match
    job.success_notes = body.success.notes

    # Update skill rows in place: keep, re-weight, remove, add.
    wanted = {skill_ids[s.name]: s.weight for s in body.skills}
    for link in list(job.skills):
        if link.skill_id in wanted:
            link.weight = wanted.pop(link.skill_id)
        else:
            job.skills.remove(link)
    for skill_id, weight in wanted.items():
        job.skills.append(JobSkill(skill_id=skill_id, weight=weight))


def create_job(db: Session, employer: User, body: JobIn) -> JobOut:
    job = Job(id=new_id("job"), employer_id=employer.id, company=employer.company or employer.name)
    _apply_job_fields(db, job, body)
    db.add(job)
    db.commit()
    db.expire_all()
    return JobOut.from_job(get_job(db, job.id), applicant_count=0)


def _applicant_count(db: Session, job_id: str) -> int:
    return len(db.scalars(select(Application.id).where(Application.job_id == job_id)).all())


def update_job(db: Session, job_id: str, employer: User, body: JobIn) -> JobOut:
    job = get_owned_job(db, job_id, employer)
    _apply_job_fields(db, job, body)
    db.commit()
    db.expire_all()
    return JobOut.from_job(get_job(db, job_id), _applicant_count(db, job_id))


def set_job_status(db: Session, job_id: str, employer: User, new_status: str) -> JobOut:
    job = get_owned_job(db, job_id, employer)
    job.status = new_status
    db.commit()
    return JobOut.from_job(job, _applicant_count(db, job_id))


# ---------- applications ----------

def apply_to_job(db: Session, job_id: str, candidate: User, consent: bool) -> ApplicationOut:
    job = db.get(Job, job_id)
    if job is None or job.status != "open":
        raise _error(status.HTTP_404_NOT_FOUND, "This job is no longer open for applications.")
    already = "You've already applied to this job."
    if db.scalars(select(Application).where(Application.job_id == job_id, Application.candidate_id == candidate.id)).first():
        raise _error(status.HTTP_409_CONFLICT, already)

    application = Application(id=new_id("app"), job_id=job_id, candidate_id=candidate.id, consent=consent, status="new")
    db.add(application)
    if consent:
        # Consent means "share my CV match and interview results with this employer".
        profile = db.get(CandidateProfile, candidate.id)
        if profile is None:
            profile = CandidateProfile(user_id=candidate.id, skills=[])
            db.add(profile)
        profile.share_with_employers = True
        profile.consent_at = profile.consent_at or datetime.now(timezone.utc)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise _error(status.HTTP_409_CONFLICT, already) from None
    db.refresh(application)
    return ApplicationOut.from_application(application)


def withdraw_application(db: Session, job_id: str, candidate: User) -> None:
    application = db.scalars(
        select(Application).where(Application.job_id == job_id, Application.candidate_id == candidate.id)
    ).first()
    if application is not None:
        db.delete(application)
        db.commit()


def set_application_status(db: Session, application_id: str, employer: User, new_status: str) -> ApplicationOut:
    application = db.scalars(
        select(Application).where(Application.id == application_id).options(selectinload(Application.job))
    ).first()
    if application is None:
        raise _error(status.HTTP_404_NOT_FOUND, "This application could not be found.")
    if application.job.employer_id != employer.id:
        raise _error(status.HTTP_403_FORBIDDEN, "Only the employer who posted this job can do that.")
    application.status = new_status
    db.commit()
    return ApplicationOut.from_application(application)


# ---------- ranked candidates ----------

def _session_for_employer(session: InterviewSession) -> dict:
    """A Session as API.md describes it, minus anything private: answer text, follow-up
    answers and video (face) indicators are never sent to employers."""
    return {
        "id": session.id,
        "userId": session.candidate_id,
        "roleId": session.role_id,
        "roleTitle": session.role.title if session.role else "",
        "mode": session.mode,
        "date": to_ms(session.date),
        "score": session.score,
        "answers": [
            {
                "questionId": a.question_id,
                "question": a.question,
                "skill": a.skill.name if a.skill else "",
                "type": a.type,
                "score": a.score,
                "criteria": a.criteria or {},
                "answer": "",
                "reason": a.reason,
                "followUp": None,
                "indicators": None,
            }
            for a in session.answers
        ],
    }


def _profile_for_employer(profile: CandidateProfile, summary: dict | None) -> dict:
    """Skills plus the three CV facts the employer screen shows; no contact details or CV text."""
    out = {"skills": profile.skills or [], "shareWithEmployers": True, "roleId": profile.target_role_id}
    if summary:
        out["cv"] = {
            "education": [{"degree": summary["topDegree"]}] if summary["topDegree"] else [],
            "experienceYears": summary["experienceYears"],
            "projects": [{"name": p.get("name", "")} for p in (profile.cv.get("projects") or [])],
        }
    return out


def ranked_candidates(db: Session, job_id: str, employer: User) -> dict:
    """Applicants for one job, best fit first. Evidence is returned only for applicants who
    consented on this application AND share their profile with employers; the rest are
    counted in `hidden` with no details."""
    job = get_owned_job(db, job_id, employer)
    job_out = JobOut.from_job(job).model_dump(by_alias=True)

    applications = db.scalars(
        select(Application)
        .where(Application.job_id == job_id)
        .options(selectinload(Application.candidate).selectinload(User.profile))
    ).all()
    visible = [
        a for a in applications
        if a.consent and a.candidate.profile is not None and a.candidate.profile.share_with_employers
    ]
    job_out["applicantCount"] = len(applications)

    sessions_by_candidate: dict[str, list[dict]] = {a.candidate_id: [] for a in visible}
    if visible:
        sessions = db.scalars(
            select(InterviewSession)
            .where(InterviewSession.candidate_id.in_(sessions_by_candidate))
            .options(
                selectinload(InterviewSession.answers).selectinload(SessionAnswer.skill),
                selectinload(InterviewSession.role),
            )
            .order_by(InterviewSession.date)
        )
        for s in sessions:
            sessions_by_candidate[s.candidate_id].append(_session_for_employer(s))

    config = {"rules": load_rules(db), "skills": load_skills(db)}
    candidates = []
    for application in visible:
        user, profile = application.candidate, application.candidate.profile
        sessions = sessions_by_candidate[user.id]
        summary = cv_summary(profile.cv)
        candidates.append({
            "application": ApplicationOut.from_application(application).model_dump(by_alias=True),
            "candidate": {"id": user.id, "name": user.name, "email": user.email},
            "profile": _profile_for_employer(profile, summary),
            "cvSummary": summary,
            "sessions": sessions,
            "fit": suitability(job_out, {"skills": profile.skills or []}, sessions, config),
        })
    candidates.sort(key=lambda c: c["fit"]["total"], reverse=True)

    return {"job": job_out, "hidden": len(applications) - len(visible), "candidates": candidates}
