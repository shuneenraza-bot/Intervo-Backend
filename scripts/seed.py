"""Seeds the database with the configuration (scripts/seed_config.py) and the demo data of the frontend's src/data.js.

Run from the project root, after `alembic upgrade head`:

    python -m scripts.seed

Safe to run again: demo rows that already exist are left untouched, except that demo
candidate profiles without a CV get their demo CV filled in. The configuration is upserted
by name (see scripts/seed_config.py).
"""

from datetime import datetime, timedelta, timezone

from app.db import SessionLocal, new_id
from app.models import (
    Application,
    ApplicationStatusEvent,
    CandidateProfile,
    Domain,
    EvaluationCriterion,
    InterviewSession,
    Job,
    JobRole,
    JobSkill,
    QuestionTemplate,
    RoleSkill,
    ScoringRules,
    SessionAnswer,
    Skill,
    User,
)
from app.services.security import hash_password
from scripts import seed_config
from app.services.matching import js_round  # rounds like the frontend's Math.round

NOW = datetime.now(timezone.utc)


def days_ago(n: int) -> datetime:
    return NOW - timedelta(days=n)


# ---------------- Configuration ----------------
# Domains, roles, skills and question templates live in scripts/seed_config.py.

QUESTIONS = seed_config.QUESTIONS

# (key, label, weight, applies_to)
CRITERIA = [
    ("technical", "Technical accuracy", 2, "technical"),
    ("relevance", "Relevance", 2, "all"),
    ("completeness", "Completeness", 2, "all"),
    ("clarity", "Clarity", 1, "all"),
    ("communication", "Communication", 1, "all"),
    ("star", "STAR structure", 2, "behavioral"),
]

RULES = {
    "weakThreshold": 60,
    "weakMinSessions": 2,
    "followUpBelow": 55,
    "defaultQuestions": 5,
    "faceThreshold": 0.55,
}

# ---------------- Demo users & data ----------------

# (id, role, name, email, company, password, created days ago)
USERS = [
    ("adm-1", "admin", "Intervo Admin", "admin@intervo.demo", None, "Admin@1234", 60),
    ("nsx-1", "employer", "Hira Malik", "hr@northstar.demo", "Northstar Digital", "Demo@1234", 40),
    ("cand-1", "candidate", "Ayesha Khan", "ayesha@intervo.demo", None, "Demo@1234", 30),
    ("cand-2", "candidate", "Bilal Ahmed", "bilal@intervo.demo", None, "Demo@1234", 25),
    ("cand-3", "candidate", "Sana Iqbal", "sana@intervo.demo", None, "Demo@1234", 20),
]

# user_id -> (skills, target role)
PROFILES = {
    "cand-1": (["React", "JavaScript", "HTML", "CSS", "Git", "Communication"], "frontend"),
    "cand-2": (["JavaScript", "HTML", "CSS", "Teamwork", "Figma"], "frontend"),
    "cand-3": (["React", "TypeScript", "CSS", "HTML", "Git", "Testing", "Communication"], "frontend"),
}

# user_id -> (degree, institution, dates, experience years, [(project, tech)])
# Parsed-CV details for the demo candidates, so employers see a CV summary.
CVS = {
    "cand-1": ("BS Computer Science", "University of Gujrat", "2021 – 2025", 0.5,
               [("Student Portal", ["React", "JavaScript"]), ("Recipe Finder", ["React", "CSS"]), ("Portfolio Site", ["HTML", "CSS"])]),
    "cand-2": ("BS Information Technology", "University of the Punjab", "2020 – 2024", 0,
               [("Landing Page Redesign", ["HTML", "CSS"]), ("Quiz App", ["JavaScript"])]),
    "cand-3": ("BS Software Engineering", "COMSATS University", "2019 – 2023", 1.5,
               [("Task Board", ["React", "TypeScript"]), ("Design System", ["React", "CSS"]),
                ("Booking Widget", ["TypeScript"]), ("Test Harness", ["Testing"])]),
}


def demo_cv(user_id: str, name: str, email: str, skills: list[str]) -> dict:
    """A ParsedCV (see API.md) for a demo candidate."""
    degree, institution, dates, years, projects = CVS[user_id]
    experience = (
        [{"title": "Frontend Intern", "company": "Local Software House", "dates": "", "details": "", "months": round(years * 12)}]
        if years else []
    )
    return {
        "contact": {"name": name, "email": email, "phone": "", "linkedin": "", "github": "", "location": "Pakistan"},
        "summary": "",
        "skills": skills,
        "otherSkills": [],
        "education": [{"degree": degree, "institution": institution, "dates": dates, "score": ""}],
        "experience": experience,
        "projects": [{"name": p, "details": "", "tech": tech} for p, tech in projects],
        "certifications": [],
        "experienceYears": years,
        "sectionsFound": ["education", "skills", "projects"] + (["experience"] if years else []),
        "warnings": [],
    }


# (user_id, role_id, days ago, [(skill, score)])
SESSIONS = [
    ("cand-1", "frontend", 12, [("React", 64), ("JavaScript", 70), ("CSS", 58), ("Communication", 66)]),
    ("cand-1", "frontend", 5, [("React", 76), ("CSS", 62), ("Testing", 48), ("Communication", 74)]),
    ("cand-1", "frontend", 1, [("React", 82), ("JavaScript", 79), ("Testing", 55), ("Git", 72)]),
    ("cand-2", "frontend", 8, [("JavaScript", 55), ("CSS", 70), ("Teamwork", 78), ("React", 46)]),
    ("cand-2", "frontend", 2, [("React", 52), ("JavaScript", 60), ("Communication", 69)]),
    ("cand-3", "frontend", 6, [("React", 84), ("Testing", 78), ("CSS", 80), ("Communication", 71)]),
]

JOBS = [
    dict(id="job-1", employer_id="nsx-1", company="Northstar Digital", title="Junior Frontend Developer", role_id="frontend",
         location="Lahore", mode="Remote", level="Entry level", type="Full-time", days=9,
         description="Build accessible, responsive interfaces alongside a small product team shipping weekly.",
         skills=[("React", 3), ("JavaScript", 3), ("CSS", 2), ("Git", 1), ("Testing", 1)],
         min_match=60, success_notes="Comfortable explaining component design and responsive layouts."),
    dict(id="job-2", employer_id="nsx-1", company="Northstar Digital", title="Web Developer Intern", role_id="frontend",
         location="Lahore", mode="Hybrid", level="Internship", type="Internship", days=4,
         description="Pair with senior developers on client websites and learn a production review workflow.",
         skills=[("HTML", 2), ("CSS", 2), ("JavaScript", 2), ("Git", 1)],
         min_match=50, success_notes="Eagerness to learn and clear communication."),
    dict(id="job-3", employer_id=None, company="Vertex Systems", title="Junior Software Engineer", role_id="backend",
         location="Karachi", mode="On-site", level="Entry level", type="Full-time", days=7,
         description="Contribute to features, tests and maintenance for internal business applications.",
         skills=[("Python", 3), ("SQL", 3), ("REST APIs", 2), ("Problem solving", 2)],
         min_match=60, success_notes=""),
    dict(id="job-4", employer_id=None, company="Crescent Analytics", title="Associate Business Analyst", role_id="analyst",
         location="Lahore", mode="Hybrid", level="Entry level", type="Full-time", days=3,
         description="Turn stakeholder questions into clear reports and help teams make data-backed decisions.",
         skills=[("Data analysis", 3), ("Excel", 3), ("SQL", 2), ("Communication", 2)],
         min_match=60, success_notes=""),
    dict(id="job-5", employer_id=None, company="Indus Media Co.", title="Marketing Trainee", role_id="marketing",
         location="Gujrat", mode="On-site", level="Internship", type="Internship", days=1,
         description="Support campaign planning, social content and performance tracking for regional brands.",
         skills=[("Campaign planning", 3), ("Market research", 2), ("Communication", 2), ("Teamwork", 1)],
         min_match=50, success_notes=""),
]

# (id, job_id, candidate_id, days ago)
APPLICATIONS = [
    ("app-1", "job-1", "cand-1", 2),
    ("app-2", "job-1", "cand-2", 3),
    ("app-3", "job-1", "cand-3", 1),
    ("app-4", "job-2", "cand-2", 1),
]


def seed() -> None:
    added = 0

    with SessionLocal() as db:

        def add_if_missing(model, pk, build) -> bool:
            nonlocal added
            if db.get(model, pk) is not None:
                return False
            db.add(build())
            added += 1
            return True

        seed_config.apply(db)

        for key, label, weight, applies_to in CRITERIA:
            add_if_missing(EvaluationCriterion, key, lambda: EvaluationCriterion(
                key=key, label=label, weight=weight, applies_to=applies_to, enabled=True))

        add_if_missing(ScoringRules, 1, lambda: ScoringRules(id=1, data=RULES))
        db.flush()

        for id_, role, name, email, company, password, days in USERS:
            if add_if_missing(User, id_, lambda: User(
                id=id_, role=role, name=name, email=email, company=company,
                password_hash=hash_password(password), created_at=days_ago(days),
            )) and id_ in PROFILES:
                skills, role_id = PROFILES[id_]
                db.add(CandidateProfile(user_id=id_, skills=skills, target_role_id=role_id,
                                        cv=demo_cv(id_, name, email, skills),
                                        share_with_employers=True, consent_at=days_ago(days)))
        db.flush()

        # Demo profiles seeded before CVs existed: fill in the CV, leave everything else alone.
        for id_, _, name, email, *_ in USERS:
            profile = db.get(CandidateProfile, id_) if id_ in CVS else None
            if profile is not None and profile.cv is None:
                profile.cv = demo_cv(id_, name, email, profile.skills or PROFILES[id_][0])
                added += 1

        for job in JOBS:
            j = dict(job)
            skills, days = j.pop("skills"), j.pop("days")
            if add_if_missing(Job, j["id"], lambda: Job(**j, status="open", created_at=days_ago(days))):
                db.add_all(JobSkill(job_id=j["id"], skill_id=seed_config.slug(s), weight=w) for s, w in skills)
        db.flush()

        for id_, job_id, candidate_id, days in APPLICATIONS:
            add_if_missing(Application, id_, lambda: Application(
                id=id_, job_id=job_id, candidate_id=candidate_id, consent=True, status="applied", created_at=days_ago(days),
                history=[ApplicationStatusEvent(id=f"hist-{id_}", status="applied", created_at=days_ago(days))]))

        question_for = {}
        for q in QUESTIONS:
            question_for.setdefault(q[1], q)

        def clamp(v: int) -> int:
            return max(20, min(98, v))

        for user_id, role_id, days, scores in SESSIONS:
            session_id = f"s-{user_id}-{days}"
            if db.get(InterviewSession, session_id) is not None:
                continue
            answers = []
            for position, (skill, score) in enumerate(scores):
                q_id, _, q_type, q_text, _, _ = question_for.get(skill, QUESTIONS[0])
                criteria = {"relevance": clamp(score + 4), "completeness": clamp(score - 4),
                            "clarity": clamp(score + 3), "communication": clamp(score + 1)}
                criteria["technical" if q_type == "technical" else "star"] = clamp(score - (2 if q_type == "technical" else 3))
                answers.append(SessionAnswer(
                    id=new_id("ans"), skill_id=seed_config.slug(skill), question_id=q_id, position=position,
                    question=q_text, type=q_type, score=score, criteria=criteria, answer=""))
            db.add(InterviewSession(
                id=session_id, candidate_id=user_id, role_id=role_id, mode="text", date=days_ago(days),
                score=js_round(sum(s for _, s in scores) / len(scores)), answers=answers))
            added += 1

        db.commit()

    print(f"Seed complete: {added} rows added or filled in (other existing rows were left unchanged).")
    print("Demo sign-ins: ayesha@intervo.demo / Demo@1234 (candidate), "
          "hr@northstar.demo / Demo@1234 (employer), admin@intervo.demo / Admin@1234 (admin)")


if __name__ == "__main__":
    seed()
