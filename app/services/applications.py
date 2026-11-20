"""Application status flow: applied -> shortlisted -> accepted | declined_by_candidate.
The employer can also stop an application (not_progressing). Contact details are shared
only after the candidate accepts."""

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db import new_id
from app.models import Application, ApplicationStatusEvent, Job, User
from app.schemas.applications import EmployerContact, HistoryItem, MyApplication
from app.schemas.base import to_ms
from app.schemas.jobs import ApplicationOut
from app.services.notifications import notify

# statuses the employer may move FROM, per target
_EMPLOYER_FROM = {
    "shortlisted": {"applied", "not_progressing"},
    "not_progressing": {"applied", "shortlisted"},
}
_RESPONDED = ("accepted", "declined_by_candidate")

_LOAD = (selectinload(Application.job).selectinload(Job.employer), selectinload(Application.history))


def _error(code: int, detail: str) -> HTTPException:
    return HTTPException(code, detail=detail)


def record(db: Session, application: Application, new_status: str, *, employer_message: str | None = None,
           candidate_note: str | None = None) -> None:
    """Sets the status and appends the history row. The caller commits."""
    application.status = new_status
    application.history.append(ApplicationStatusEvent(
        id=new_id("hist"), status=new_status, employer_message=employer_message, candidate_note=candidate_note,
    ))
    db.flush()  # gives the new history row its created_at


def _load(db: Session, application_id: str) -> Application:
    application = db.scalars(select(Application).where(Application.id == application_id).options(*_LOAD)).first()
    if application is None:
        raise _error(status.HTTP_404_NOT_FOUND, "This application could not be found.")
    return application


# ---------- employer ----------

def set_application_status(db: Session, application_id: str, employer: User, new_status: str,
                           message: str | None) -> ApplicationOut:
    application = _load(db, application_id)
    job = application.job
    if job.employer_id != employer.id:
        raise _error(status.HTTP_403_FORBIDDEN, "Only the employer who posted this job can do that.")
    if application.status not in _EMPLOYER_FROM[new_status]:
        raise _error(
            status.HTTP_409_CONFLICT,
            "The candidate has already responded to this application." if application.status in _RESPONDED
            else f"This application is already {application.status.replace('_', ' ')}.",
        )
    message = (message or "").strip() or None
    record(db, application, new_status, employer_message=message)

    said = f' They said: "{message}"' if message else ""
    if new_status == "shortlisted":
        notify(db, application.candidate_id, "shortlisted", f"You've been shortlisted for {job.title}",
               f"{job.company} would like to move forward with your application.{said} "
               "Accept or decline in My Applications.", "/applications")
    else:
        notify(db, application.candidate_id, "not_progressing", f"Update on your application for {job.title}",
               f"{job.company} won't be moving forward with your application.{said}", "/applications")
    db.commit()
    return ApplicationOut.from_application(application)


# ---------- candidate ----------

def _my_application(application: Application) -> MyApplication:
    job, events = application.job, application.history
    out = ApplicationOut.from_application(application)
    employer = None
    if application.status == "accepted" and job.employer is not None:
        employer = EmployerContact(
            name=job.employer.name, company=job.employer.company or job.company, email=job.employer.email,
        )
    return MyApplication(
        id=application.id, job_id=job.id, job_title=job.title, company=job.company, status=application.status,
        employer_message=out.employer_message, candidate_note=out.candidate_note,
        applied_at=out.date, updated_at=out.updated_at,
        history=[HistoryItem(status=e.status, at=to_ms(e.created_at), employer_message=e.employer_message,
                             candidate_note=e.candidate_note) for e in events],
        employer=employer,
    )


def my_applications(db: Session, candidate: User) -> list[MyApplication]:
    rows = db.scalars(
        select(Application).where(Application.candidate_id == candidate.id)
        .options(*_LOAD).order_by(Application.created_at.desc())
    ).all()
    return [_my_application(a) for a in rows]


def respond(db: Session, application_id: str, candidate: User, decision: str, note: str | None) -> MyApplication:
    application = _load(db, application_id)
    if application.candidate_id != candidate.id:
        raise _error(status.HTTP_403_FORBIDDEN, "You can only respond to your own applications.")
    if application.status != "shortlisted":
        raise _error(
            status.HTTP_409_CONFLICT,
            "You've already responded to this application." if application.status in _RESPONDED
            else "You can only respond once you've been shortlisted.",
        )
    note = (note or "").strip() or None
    job = application.job
    accepted = decision == "accept"
    record(db, application, "accepted" if accepted else "declined_by_candidate", candidate_note=note)

    if job.employer_id:
        said = f' They said: "{note}"' if note else ""
        link = f"/candidates?job={job.id}"
        if accepted:
            notify(db, job.employer_id, "accepted", f"{candidate.name} accepted your shortlist for {job.title}",
                   f"Their contact details are now on the Candidates page.{said}", link)
        else:
            notify(db, job.employer_id, "declined", f"{candidate.name} declined your shortlist for {job.title}",
                   f"No contact details were shared.{said}", link)
    db.commit()
    return _my_application(application)
