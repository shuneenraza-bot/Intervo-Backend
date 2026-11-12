"""Seeds the database with the same configuration and demo data as the frontend's src/data.js.

Run from the project root, after `alembic upgrade head`:

    python -m scripts.seed

Safe to run again: rows that already exist are left untouched, except that demo
candidate profiles without a CV get their demo CV filled in.
"""

import re
from datetime import datetime, timedelta, timezone

from app.db import SessionLocal, new_id
from app.models import (
    Application,
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
from app.services.suitability import js_round  # rounds like the frontend's Math.round

NOW = datetime.now(timezone.utc)


def days_ago(n: int) -> datetime:
    return NOW - timedelta(days=n)


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


# ---------------- Configuration ----------------

DOMAINS = [("tech", "Technology"), ("business", "Business"), ("marketing", "Marketing"), ("hrfin", "HR & Finance")]

# (name, aliases, related, tip)
SKILLS = [
    ("React", ["react", "reactjs", "react.js"], ["JavaScript"], "Practise explaining state, props and component re-renders with a small example."),
    ("JavaScript", ["javascript", "js", "es6"], ["TypeScript", "React"], "Review scope, closures and async/await, then explain each out loud in two sentences."),
    ("TypeScript", ["typescript", "ts"], ["JavaScript"], "Be ready to explain why types catch bugs earlier, with one real example."),
    ("HTML", ["html", "html5", "semantic html"], ["CSS"], "Mention semantic tags and accessibility when describing page structure."),
    ("CSS", ["css", "css3", "tailwind", "bootstrap", "sass", "flexbox", "grid"], ["HTML"], "Explain responsive layouts with flexbox/grid and media queries step by step."),
    ("Git", ["git", "github", "version control", "pull request"], [], "Describe your branch → commit → pull request → review flow in order."),
    ("REST APIs", ["api", "apis", "rest", "restful", "endpoint", "fastapi"], ["Node.js", "Python"], "Use one concrete endpoint example and mention status codes and validation."),
    ("SQL", ["sql", "postgresql", "mysql", "query", "database"], ["Data analysis"], "Walk through a query with GROUP BY and a JOIN, and say why indexes matter."),
    ("Python", ["python", "pandas", "django", "flask"], ["REST APIs"], "Explain error handling with try/except and give a file-reading example."),
    ("Node.js", ["node", "nodejs", "node.js", "express"], ["JavaScript", "REST APIs"], "Explain the event loop in simple words and when async matters."),
    ("Testing", ["testing", "jest", "unit test", "unit testing", "qa", "pytest"], [], "Give an example of a unit test: what you test, the input, and the expected result."),
    ("Figma", ["figma", "ui/ux", "prototyping", "wireframe", "wireframes"], [], "Describe how you move from wireframe to prototype and gather feedback."),
    ("Communication", ["communication", "presentation", "explain", "stakeholder"], ["Teamwork"], "Answer in three parts: headline, one example, the result. Keep sentences short."),
    ("Teamwork", ["teamwork", "collaboration", "team", "collaborative"], ["Communication", "Leadership"], "Pick a team conflict story and practise it in STAR format."),
    ("Problem solving", ["problem solving", "problem-solving", "analytical", "debugging", "root cause"], [], "Show your steps: understand, break down, try, verify. Name the result."),
    ("Excel", ["excel", "spreadsheets", "vlookup", "pivot"], ["Data analysis"], "Prepare a pivot-table or lookup example from a real report you made."),
    ("Data analysis", ["data analysis", "analytics", "power bi", "tableau", "insights"], ["Excel", "SQL"], "Structure answers as question → data → finding → recommendation."),
    ("Leadership", ["leadership", "mentoring", "lead", "led"], ["Teamwork"], "Prepare one story where you took ownership and what changed because of it."),
    ("Marketing", ["marketing", "seo", "social media", "campaign", "campaigns", "engagement"], ["Data analysis"], "Always connect campaigns to a measurable goal like reach, CTR or conversions."),
    ("Recruitment", ["recruitment", "talent acquisition", "sourcing", "onboarding", "screening candidates"], ["Communication"], "Explain a hiring pipeline stage by stage and how you measure quality of hire."),
    ("Accounting", ["accounting", "bookkeeping", "ledger", "reconciliation", "financial statements"], ["Excel"], "Walk through a reconciliation example and how you find discrepancies."),
]

# (id, title, domain_id, [(skill, weight)])
ROLES = [
    ("frontend", "Frontend Developer", "tech", [("React", 3), ("JavaScript", 3), ("CSS", 2), ("HTML", 2), ("Git", 1), ("Testing", 1), ("Communication", 1)]),
    ("backend", "Backend Developer", "tech", [("Python", 3), ("SQL", 3), ("REST APIs", 3), ("Git", 1), ("Testing", 2), ("Problem solving", 2)]),
    ("analyst", "Business Analyst", "business", [("Data analysis", 3), ("Excel", 3), ("SQL", 2), ("Communication", 3), ("Problem solving", 2)]),
    ("marketing", "Marketing Associate", "marketing", [("Marketing", 3), ("Communication", 3), ("Data analysis", 2), ("Teamwork", 2), ("Excel", 1)]),
    ("hr", "HR Associate", "hrfin", [("Recruitment", 3), ("Communication", 3), ("Teamwork", 2), ("Excel", 1)]),
    ("accounts", "Junior Accountant", "hrfin", [("Accounting", 3), ("Excel", 3), ("Problem solving", 2), ("Communication", 1)]),
]

# (id, skill, type, text, keywords, follow_up)
QUESTIONS = [
    ("q1", "Communication", "behavioral", "Tell me about yourself and the strengths you would bring to this role.", ["experience", "project", "skill", "team", "learned"], "Which one of those strengths has made the biggest difference in a project, and how?"),
    ("q2", "Problem solving", "behavioral", "Describe a difficult problem you solved. What was the situation and what did you do?", ["problem", "steps", "tested", "result", "cause"], "How did you confirm that your solution actually fixed the problem?"),
    ("q3", "Teamwork", "behavioral", "Tell me about a time you disagreed with a teammate. How did you resolve it?", ["listened", "agreed", "compromise", "discussed", "outcome"], "Looking back, what would you do differently in that disagreement?"),
    ("q4", "React", "technical", "How do you decide what belongs in component state versus props in a React app?", ["state", "props", "parent", "child", "re-render", "lift"], "What happens when two sibling components need the same piece of state?"),
    ("q5", "JavaScript", "technical", "Explain the difference between let, const and var, and when you would use each.", ["scope", "block", "hoisting", "reassign", "function"], "Can you give a short example where using var causes a bug?"),
    ("q6", "CSS", "technical", "How would you build a layout that works well on both mobile and desktop screens?", ["flexbox", "grid", "media", "responsive", "breakpoint", "mobile"], "Which breakpoints would you choose and why?"),
    ("q7", "SQL", "technical", "How would you find duplicate records in a table, and how would you prevent them?", ["group by", "having", "count", "unique", "constraint", "index"], "How would you delete the duplicates but keep one copy of each row?"),
    ("q8", "REST APIs", "technical", "What makes a REST API well designed? Give an example endpoint you would create.", ["resource", "get", "post", "status", "json", "validation"], "Which status codes would that endpoint return on success and on errors?"),
    ("q9", "Python", "technical", "How do you handle errors in a Python program that reads data from a file?", ["try", "except", "finally", "with", "filenotfound", "log"], "Why is the with statement useful when opening files?"),
    ("q10", "Data analysis", "technical", "Walk me through how you would analyse why sales dropped last month.", ["data", "compare", "segment", "trend", "cause", "recommend"], "Which chart would you show a manager to explain your finding?"),
    ("q11", "Marketing", "technical", "How would you measure whether a social media campaign was successful?", ["goal", "reach", "engagement", "conversion", "ctr", "audience"], "If engagement was high but conversions were low, what would you change?"),
    ("q12", "Git", "technical", "Describe your Git workflow when working on a feature with other developers.", ["branch", "commit", "pull request", "review", "merge", "conflict"], "How do you resolve a merge conflict?"),
    ("q13", "HTML", "technical", "Why does semantic HTML matter, and which tags do you use most?", ["semantic", "accessibility", "header", "nav", "main", "screen reader"], "How does semantic HTML help screen-reader users?"),
    ("q14", "Testing", "technical", "How do you decide what to test in a new feature?", ["unit", "edge case", "input", "expected", "integration", "bug"], "Give an example of an edge case you would test."),
    ("q15", "Excel", "technical", "How would you summarise a large sales sheet by region and month in Excel?", ["pivot", "sumifs", "filter", "chart", "region", "month"], "How would you keep that summary up to date when new rows are added?"),
    ("q16", "Recruitment", "technical", "How would you design a fair screening process for an entry-level role?", ["criteria", "structured", "bias", "shortlist", "interview", "consistent"], "How would you check the process is actually fair after a hiring round?"),
    ("q17", "Accounting", "technical", "How would you approach a bank reconciliation that doesn't balance?", ["statement", "ledger", "difference", "timing", "error", "adjust"], "What are common causes of timing differences?"),
    ("q18", "Leadership", "behavioral", "Tell me about a time you took the lead on something without being asked.", ["initiative", "team", "plan", "result", "responsibility"], "How did the rest of the team respond to you taking the lead?"),
]

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
    "suitability": {"cv": 40, "interview": 45, "consistency": 15},
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
         min_score=65, min_match=60, success_notes="Comfortable explaining component design and responsive layouts."),
    dict(id="job-2", employer_id="nsx-1", company="Northstar Digital", title="Web Developer Intern", role_id="frontend",
         location="Lahore", mode="Hybrid", level="Internship", type="Internship", days=4,
         description="Pair with senior developers on client websites and learn a production review workflow.",
         skills=[("HTML", 2), ("CSS", 2), ("JavaScript", 2), ("Git", 1)],
         min_score=55, min_match=50, success_notes="Eagerness to learn and clear communication."),
    dict(id="job-3", employer_id=None, company="Vertex Systems", title="Junior Software Engineer", role_id="backend",
         location="Karachi", mode="On-site", level="Entry level", type="Full-time", days=7,
         description="Contribute to features, tests and maintenance for internal business applications.",
         skills=[("Python", 3), ("SQL", 3), ("REST APIs", 2), ("Problem solving", 2)],
         min_score=65, min_match=60, success_notes=""),
    dict(id="job-4", employer_id=None, company="Crescent Analytics", title="Associate Business Analyst", role_id="analyst",
         location="Lahore", mode="Hybrid", level="Entry level", type="Full-time", days=3,
         description="Turn stakeholder questions into clear reports and help teams make data-backed decisions.",
         skills=[("Data analysis", 3), ("Excel", 3), ("SQL", 2), ("Communication", 2)],
         min_score=60, min_match=60, success_notes=""),
    dict(id="job-5", employer_id=None, company="Indus Media Co.", title="Marketing Trainee", role_id="marketing",
         location="Gujrat", mode="On-site", level="Internship", type="Internship", days=1,
         description="Support campaign planning, social content and performance tracking for regional brands.",
         skills=[("Marketing", 3), ("Communication", 2), ("Teamwork", 1)],
         min_score=55, min_match=50, success_notes=""),
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

        for id_, name in DOMAINS:
            add_if_missing(Domain, id_, lambda: Domain(id=id_, name=name))

        for name, aliases, related, tip in SKILLS:
            add_if_missing(Skill, slug(name), lambda: Skill(id=slug(name), name=name, aliases=aliases, related=related, tip=tip))
        db.flush()

        for id_, title, domain_id, role_skills in ROLES:
            if add_if_missing(JobRole, id_, lambda: JobRole(id=id_, title=title, domain_id=domain_id)):
                db.add_all(RoleSkill(role_id=id_, skill_id=slug(s), weight=w) for s, w in role_skills)

        for id_, skill, type_, text, keywords, follow_up in QUESTIONS:
            add_if_missing(QuestionTemplate, id_, lambda: QuestionTemplate(
                id=id_, skill_id=slug(skill), type=type_, text=text, keywords=keywords, follow_up=follow_up))

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
                db.add_all(JobSkill(job_id=j["id"], skill_id=slug(s), weight=w) for s, w in skills)
        db.flush()

        for id_, job_id, candidate_id, days in APPLICATIONS:
            add_if_missing(Application, id_, lambda: Application(
                id=id_, job_id=job_id, candidate_id=candidate_id, consent=True, status="new", created_at=days_ago(days)))

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
                    id=new_id("ans"), skill_id=slug(skill), question_id=q_id, position=position,
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
