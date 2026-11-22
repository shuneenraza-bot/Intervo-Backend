"""CV and job-description analysis: AI (or rules) extraction, normalisation against the skill
library, storage on the candidate profile, and deterministic matching."""

from fastapi import HTTPException, status
from sqlalchemy.orm import Session, selectinload

from app.models import CandidateProfile, JobRole, RoleSkill, User
from app.schemas.cv import (
    LLMCV,
    LLMJD,
    CVFileOut,
    CVResponse,
    JDParseIn,
    JDParseOut,
    JDSkill,
    MatchIn,
    MatchOut,
    ParsedCV,
)
from app.schemas.base import to_ms
from app.services import cv_files, cv_rules
from app.services.ai import run_json_task
from app.services.ai.prompts import cv_prompt, jd_prompt, strip_contact
from app.services.catalog import load_skills, weighted_skills


def _canonical(names: list[str], lookup: dict[str, str]) -> tuple[list[str], list[str]]:
    """Splits raw skill strings into (library skill names, everything else), keeping order."""
    known: dict[str, None] = {}
    other: dict[str, None] = {}
    for raw in names:
        raw = str(raw).strip()
        if not raw:
            continue
        hit = lookup.get(raw.lower())
        if hit:
            known.setdefault(hit, None)
        else:
            other.setdefault(raw[:28], None)
    return list(known), list(other)


def _sections_found(cv: ParsedCV) -> list[str]:
    present = {
        "summary": cv.summary, "education": cv.education, "experience": cv.experience,
        "projects": cv.projects, "skills": cv.skills or cv.other_skills, "certifications": cv.certifications,
    }
    return [k for k, v in present.items() if v]


# ---------- CV ----------

def build_cv(llm: LLMCV, text: str, skills: list[dict]) -> ParsedCV:
    """Provider output + application-side rules -> the ParsedCV the frontend uses.

    Contact details always come from local rules (they were never sent to the AI). Skills
    are matched to the library by name/alias; the rest go to otherSkills."""
    lookup = cv_rules.skill_lookup(skills)
    known, extra = _canonical(llm.skills, lookup)
    for name in cv_rules.extract_skills(text, skills):  # deterministic safety net
        if name not in known:
            known.append(name)
    _, listed = _canonical(llm.other_skills, lookup)
    other = [s for s in dict.fromkeys([*listed, *extra]) if s.lower() not in lookup][:16]

    experience = []
    for e in llm.experience:
        item = e.model_dump()
        # Never trust AI numbers derived from dates: always computed from the date range.
        item["months"] = cv_rules.months_between(e.dates)
        experience.append(item)

    projects = []
    for p in llm.projects:
        tech, _ = _canonical(p.tech, lookup)
        for name in cv_rules.extract_skills(f"{p.name} {p.details}", skills):
            if name not in tech:
                tech.append(name)
        projects.append({"name": p.name, "details": p.details, "tech": tech})

    header = [l for l in text.split("\n") if l.strip()][:8]
    cv = ParsedCV.model_validate({
        "contact": cv_rules.parse_contact(header, text),
        "summary": llm.summary[:600],
        "skills": known,
        "other_skills": other,
        "education": [e.model_dump() for e in llm.education if e.degree or e.institution],
        "experience": [e for e in experience if e["title"]],
        "projects": [p for p in projects if p["name"]],
        "certifications": llm.certifications[:10],
        "experience_years": cv_rules.years_from_months(experience),
    })
    cv.sections_found = _sections_found(cv)
    if not cv.sections_found or cv.sections_found == ["skills"]:
        cv.warnings.append("No section headings (Education, Experience, Skills…) were found, so only skills were extracted. Add the details below if needed.")
    if not cv.skills:
        cv.warnings.append("No skills from the skill library were recognised. Add them manually below.")
    return cv


def _summary_for_employers(cv: ParsedCV) -> dict:
    """The small CV summary employers' CV match reads (no contact details, no text)."""
    return {
        "education": [{"degree": e.degree, "institution": e.institution} for e in cv.education],
        "experienceYears": cv.experience_years,
        "projects": [{"name": p.name} for p in cv.projects],
    }


def _store(db: Session, user: User, cv: ParsedCV, **extra) -> CandidateProfile:
    profile = db.get(CandidateProfile, user.id)
    if profile is None:
        profile = CandidateProfile(user_id=user.id)
        db.add(profile)
    profile.parsed_cv = cv.model_dump(by_alias=True)
    profile.cv = _summary_for_employers(cv)
    profile.skills = cv.skills
    for key, value in extra.items():
        setattr(profile, key, value)
    db.commit()
    return profile


def _response(profile: CandidateProfile) -> CVResponse:
    f = profile.cv_file
    return CVResponse(
        cv=ParsedCV.model_validate(profile.parsed_cv),
        file=CVFileOut(name=f.file_name, size=f.size_bytes, content_type=f.content_type,
                       uploaded_at=to_ms(f.created_at)) if f else None,
        provider=profile.cv_provider,
        file_name=profile.cv_file_name,
        text=profile.cv_text or "",
    )


def analyze_and_save(db: Session, user: User, text: str, file_name: str, data: bytes) -> CVResponse:
    skills = load_skills(db)
    # Only the CV text without contact details, address and the person's name goes to an AI provider.
    header = [l for l in text.split(chr(10)) if l.strip()][:8]
    names = [user.name, cv_rules.parse_contact(header, text)["name"]]
    llm, provider = run_json_task(cv_prompt(strip_contact(text, names)), LLMCV, task="cv", text=text, skills=skills)
    cv = build_cv(llm, text, skills)
    old = db.get(CandidateProfile, user.id)
    old_file_id = old.cv_file_id if old else None
    stored = cv_files.add_file(db, user.id, file_name, data)
    try:
        profile = _store(db, user, cv, cv_text=text, cv_file_name=file_name, cv_provider=provider,
                         cv_file_id=stored.id)
    except Exception:
        db.rollback()
        cv_files.remove_stored([stored.storage_name])
        raise
    # The previous file goes unless an application still holds it as the employer's snapshot.
    gone = cv_files.discard_if_unused(db, old_file_id)
    db.commit()
    cv_files.remove_stored(gone)
    return _response(profile)


def get_saved(db: Session, user: User) -> CVResponse:
    profile = db.get(CandidateProfile, user.id)
    if profile is None or not profile.parsed_cv:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="You haven't uploaded a CV yet.")
    return _response(profile)


def save_edits(db: Session, user: User, body: ParsedCV) -> CVResponse:
    """The user's own corrections replace the stored CV. Skills are re-checked against the library."""
    lookup = cv_rules.skill_lookup(load_skills(db))
    known, extra = _canonical(body.skills, lookup)
    cv = body.model_copy(deep=True)
    cv.skills = known
    cv.other_skills = [s for s in dict.fromkeys([*body.other_skills, *extra]) if s.lower() not in lookup][:30]
    for p in cv.projects:
        p.tech = _canonical(p.tech, lookup)[0]
    cv.sections_found = _sections_found(cv)
    cv.warnings = []
    return _response(_store(db, user, cv))


# ---------- job description ----------

def parse_jd(db: Session, body: JDParseIn) -> JDParseOut:
    skills = load_skills(db)
    lookup = cv_rules.skill_lookup(skills)
    role_skills = [{"name": s.name, "weight": s.weight} for s in body.role_skills]
    llm, provider = run_json_task(
        jd_prompt(body.text), LLMJD, task="jd", text=body.text, skills=skills, role_skills=role_skills
    )

    weights: dict[str, int] = {}
    for s in llm.skills:
        name = lookup.get(s.name.lower().strip())
        if name:
            weights[name] = max(weights.get(name, 0), min(3, max(1, s.weight)))
    default = {s["name"]: s["weight"] for s in role_skills}
    for name, weight in list(weights.items()):
        if weight == 2 and name in default:
            weights[name] = default[name]
    for s in cv_rules.parse_jd(body.text, skills, role_skills)["skills"]:  # deterministic safety net
        weights.setdefault(s["name"], s["weight"])

    return JDParseOut(
        title=llm.title[:200],
        skills=[JDSkill(name=n, weight=w) for n, w in sorted(weights.items(), key=lambda kv: (-kv[1], kv[0]))],
        min_years=min(max(llm.min_years, 0), 60),
        education=llm.education[:200],
        fresher_friendly=llm.fresher_friendly,
        provider=provider,
    )


# ---------- matching (deterministic, never AI) ----------

def match(db: Session, user: User, body: MatchIn) -> MatchOut:
    if (body.role_id is None) == (body.jd is None):
        raise HTTPException(422, detail="Send either roleId or jd.")
    profile = db.get(CandidateProfile, user.id)
    if profile is None or not profile.parsed_cv:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Upload your CV first.")
    cv = ParsedCV.model_validate(profile.parsed_cv)

    jd = body.jd
    if body.role_id is not None:
        role = db.get(JobRole, body.role_id, options=[selectinload(JobRole.skills).selectinload(RoleSkill.skill)])
        if role is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="That role doesn't exist.")
        required = weighted_skills(role.skills)
    else:
        required = [{"name": s.name, "weight": s.weight} for s in jd.skills]

    result = cv_rules.match_skills(cv.skills, required, load_skills(db))
    checks = []
    if jd is not None:
        checks = cv_rules.requirement_checks(
            {"min_years": jd.min_years, "education": jd.education, "fresher_friendly": jd.fresher_friendly},
            cv.experience_years, [e.degree for e in cv.education],
        )
    return MatchOut.model_validate({**result, "checks": checks})
