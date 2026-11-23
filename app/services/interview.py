"""The adaptive interview engine: question selection, AI (or rule-based) answer evaluation,
session scoring and the candidate's progress.

Selection and skill history port `selectQuestions` and `skillPerformance` from the frontend's
src/lib.js. Scores the AI returns are clamped, and every overall score is calculated here in
Python from the admin-configured criteria weights, never by the model."""

import logging
import random
import time
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db import new_id
from app.models import (
    CandidateProfile,
    EvaluationCriterion,
    InterviewSession,
    Job,
    JobRole,
    JobSkill,
    QuestionTemplate,
    RoleSkill,
    SessionAnswer,
    Skill,
    User,
)
from app.schemas.base import to_ms
from app.schemas.interview import MAX_ANSWER_CHARS, AnswerBody, FollowUpBody, LLMEvaluation, LLMFollowUp, LLMQuestion, StartIn
from app.config import settings
from app.services import ai
from app.services.ai import RuleBasedProvider, run_json_task
from app.services.ai.prompts import RUBRIC, evaluation_prompt, follow_up_prompt, question_prompt
from app.services.catalog import load_rules, load_skills, weighted_skills
from app.services.matching import DEFAULT_RULES, average, js_round, match_skills, skill_performance

log = logging.getLogger("intervo.interview")
DEFAULTS = {**DEFAULT_RULES, "followUpBelow": 55, "defaultQuestions": 5}
# Used only when the evaluation_criteria table is empty: (key, weight, applies_to).
DEFAULT_CRITERIA = [("technical", 2, "technical"), ("relevance", 2, "all"), ("completeness", 2, "all"),
                    ("clarity", 1, "all"), ("communication", 1, "all"), ("star", 2, "behavioral")]
RANK = {"weakness": 0, "gap": 1, "role": 2, "general": 3}
BEHAVIOURAL_FALLBACK_SKILLS = ("Communication", "Teamwork", "Leadership")


def _rules(db: Session) -> dict:
    return {**DEFAULTS, **load_rules(db)}


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------- skill history (completed sessions only) ----------

def _history(db: Session, candidate_id: str) -> list[InterviewSession]:
    return list(db.scalars(
        select(InterviewSession)
        .where(InterviewSession.candidate_id == candidate_id, InterviewSession.status == "completed")
        .options(selectinload(InterviewSession.answers).selectinload(SessionAnswer.skill), selectinload(InterviewSession.role))
        .order_by(InterviewSession.date)
    ))


def _as_perf_input(sessions: list[InterviewSession]) -> list[dict]:
    return [
        {"id": s.id, "date": to_ms(s.date), "score": s.score,
         "answers": [{"skill": a.skill.name, "score": a.score} for a in s.answers if a.skill]}
        for s in sessions
    ]


# ---------- selection ----------

def _template_dict(t: QuestionTemplate, reason: str) -> dict:
    return {"template_id": t.id, "skill": t.skill.name, "type": t.type, "text": t.text,
            "keywords": t.keywords or [], "follow_up": t.follow_up or "", "reason": reason}


def _generate_question(
    db: Session, role_title: str, skill: Skill, qtype: str, reason: str, responsibilities: list[str] | None = None
) -> dict:
    """Asks the provider for one question. A Gemini question is saved as a new template marked
    "generated"; the offline stand-in is used once and not saved."""
    q, provider = run_json_task(
        question_prompt(role_title, skill.name, qtype, responsibilities), LLMQuestion,
        task="question", skill=skill.name, role=role_title, type=qtype,
    )
    template_id = None
    if provider != "rules":
        template = QuestionTemplate(
            id=new_id("q"), skill_id=skill.id, type=qtype, text=q.text, keywords=q.keywords,
            follow_up=q.follow_up, source="generated",
        )
        db.add(template)
        db.flush()
        template_id = template.id
    return {"template_id": template_id, "skill": skill.name, "type": qtype, "text": q.text,
            "keywords": q.keywords, "follow_up": q.follow_up, "reason": reason}


def select_questions(
    db: Session, role_title: str, required: list[dict], weak: list[str], gaps: list[str], count: int,
    responsibilities: list[str] | None = None,
) -> list[dict]:
    """Persistent weaknesses first, then CV gaps, then the role's highest-weighted skills, and
    always at least one behavioural question."""
    role_skills = [r["name"] for r in sorted(required, key=lambda r: -r["weight"])]
    skills = {s.name: s for s in db.scalars(select(Skill))}
    templates = db.scalars(select(QuestionTemplate).options(selectinload(QuestionTemplate.skill))).all()
    by_skill: dict[str, list[QuestionTemplate]] = {}
    for t in templates:
        by_skill.setdefault(t.skill.name, []).append(t)

    def reason(skill: str) -> str:
        return "weakness" if skill in weak else "gap" if skill in gaps else "role" if skill in role_skills else "general"

    focus = list(dict.fromkeys([*role_skills, *weak]))  # skills we ask about even without a template
    focus.sort(key=lambda s: (RANK[reason(s)], role_skills.index(s) if s in role_skills else len(role_skills)))
    behavioural = [t for t in templates if t.type == "behavioral"]
    others = [t.skill.name for t in random.sample(behavioural, len(behavioural)) if t.skill.name not in focus]

    picked: list[dict] = []
    used: set[str] = set()
    for name in [*focus, *dict.fromkeys(others)]:
        if len(picked) >= count:
            break
        if name in used:
            continue
        pool = by_skill.get(name, [])
        if name not in focus:  # only behavioural questions come from skills outside the role
            pool = [t for t in pool if t.type == "behavioral"]
        if pool:
            picked.append(_template_dict(random.choice(pool), reason(name)))
        elif name in skills:
            picked.append(_generate_question(db, role_title, skills[name], "technical", reason(name), responsibilities))
        else:
            continue
        used.add(name)

    if not any(p["type"] == "behavioral" for p in picked):
        spare = [t for t in behavioural if t.skill.name not in used]
        q = None
        if spare:
            q = _template_dict(random.choice(spare), "general")
        else:
            name = next((n for n in BEHAVIOURAL_FALLBACK_SKILLS if n in skills), None) or next(iter(role_skills), None)
            if name in skills:
                q = _generate_question(db, role_title, skills[name], "behavioral", reason(name), responsibilities)
        if q is not None:
            if len(picked) >= count:
                picked[-1] = q
            else:
                picked.append(q)
    return picked


# ---------- start ----------

def start(db: Session, user: User, body: StartIn) -> dict:
    if (body.role_id is None) == (body.job_id is None):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Send either roleId or jobId.")
    rules = _rules(db)
    job = None
    if body.job_id is not None:
        job = db.get(Job, body.job_id, options=[selectinload(Job.skills).selectinload(JobSkill.skill), selectinload(Job.role)])
        if job is None or job.status != "open":
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="That job doesn't exist or is closed.")
        role, required = job.role, weighted_skills(job.skills)
    else:
        role = db.get(JobRole, body.role_id, options=[selectinload(JobRole.skills).selectinload(RoleSkill.skill)])
        if role is None or not role.active:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="That role doesn't exist.")
        required = weighted_skills(role.skills)

    perf = skill_performance(_as_perf_input(_history(db, user.id)), rules)
    weak = [p["skill"] for p in perf if p["weak"]]
    profile = db.get(CandidateProfile, user.id)
    gaps: list[str] = []
    if profile is not None and (profile.parsed_cv or profile.skills):  # a saved CV
        match = match_skills(profile.skills or [], required, load_skills(db))
        gaps = [s["name"] for s in [*match["missing"], *match["partial"]]]

    count = body.count or int(rules["defaultQuestions"])
    questions = select_questions(db, role.title, required, weak, gaps, count, role.responsibilities or [])
    if not questions:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="No questions are available for this role yet.")

    skill_ids = {s.name: s.id for s in db.scalars(select(Skill))}
    session = InterviewSession(
        id=new_id("s"), candidate_id=user.id, role_id=role.id, job_id=job.id if job else None,
        mode=body.mode, status="in_progress", score=0, date=_now(),
        answers=[
            SessionAnswer(
                id=new_id("ans"), skill_id=skill_ids.get(q["skill"]), question_id=q["template_id"], position=i,
                question=q["text"], type=q["type"], reason=q["reason"], keywords=q["keywords"],
                follow_up_question=q["follow_up"] or None,
            )
            for i, q in enumerate(questions)
        ],
    )
    db.add(session)
    db.commit()
    return interview_out(_load(db, session.id))


# ---------- evaluation ----------

def _criteria_for(db: Session, qtype: str) -> list[tuple[str, int]]:
    rows = db.scalars(select(EvaluationCriterion).where(EvaluationCriterion.enabled.is_(True))).all()
    pairs = [(c.key, c.weight, c.applies_to) for c in rows] or DEFAULT_CRITERIA
    return [(k, w) for k, w, applies in pairs if applies in ("all", qtype) and k in RUBRIC]


def _evaluate(db: Session, rules: dict, role_title: str, row: SessionAnswer, text: str) -> dict:
    """Rubric scores from the provider, clamped; the overall score is computed here.
    Only the role, skill, question, rubric and answer text leave the server."""
    criteria = _criteria_for(db, row.type)
    keys = [k for k, _ in criteria]
    skill = row.skill.name if row.skill else "General"
    question = {"text": row.question, "keywords": row.keywords or [], "skill": skill, "type": row.type}
    aliases = (row.skill.aliases if row.skill else None) or []
    below = int(rules["followUpBelow"])
    ctx = {"task": "evaluate", "answer": text, "question": question, "aliases": aliases, "follow_up_below": below}

    def missing(ev: LLMEvaluation) -> list[str]:
        return [k for k in keys if getattr(ev, k) is None]

    prompt = evaluation_prompt(role_title, skill, row.type, row.question, row.keywords or [], keys, text)
    started = time.monotonic()
    llm, provider = run_json_task(prompt, LLMEvaluation, **ctx)
    if provider == "rules" and ai.get_provider().name != "rules" and time.monotonic() - started < settings.ai_timeout_seconds / 2:
        # Gemini is configured but the call failed fast (rate limit, brief network error). One more try
        # beats grading a whole answer, or a follow-up, with the offline evaluator. A slow failure (timeout)
        # is not retried so the candidate isn't kept waiting.
        log.warning("evaluate: Gemini failed quickly; retrying once before falling back to rules")
        llm, provider = run_json_task(prompt, LLMEvaluation, **ctx)
    if provider != "rules" and missing(llm):
        log.warning("evaluate: %s omitted criteria %s; retrying once with a stricter prompt", provider, missing(llm))
        retry, retry_provider = run_json_task(
            evaluation_prompt(role_title, skill, row.type, row.question, row.keywords or [], keys, text, strict=True),
            LLMEvaluation, **ctx)
        # If the retry itself fell back to rules, run_json_task logged why; keep Gemini's first scores.
        if retry_provider != "rules" and len(missing(retry)) < len(missing(llm)):
            llm = retry
    if provider != "rules" and missing(llm):
        gaps = missing(llm)
        log.warning("evaluate: %s still omitted criteria %s after the retry; filling only those from the rules evaluator",
                    provider, gaps)
        raw = LLMEvaluation.model_validate(RuleBasedProvider().generate_json("", LLMEvaluation, **ctx))
        llm = llm.model_copy(update={k: getattr(raw, k) for k in gaps})
        provider = f"{provider}+rules"

    scores = {k: getattr(llm, k) for k in keys}
    total_weight = sum(w for _, w in criteria) or 1
    overall = js_round(sum(scores[k] * w for k, w in criteria) / total_weight)
    return {
        "score": overall, "criteria": scores, "provider": provider,
        "tips": llm.tips or ["Add a concrete example from a project and say what the outcome was."],
        "needs_follow_up": llm.needs_follow_up or scores.get("completeness", overall) < below,
    }


def _store_evaluation(row: SessionAnswer, ev: dict) -> None:
    row.score, row.criteria, row.tips, row.provider = ev["score"], ev["criteria"], ev["tips"], ev["provider"]
    row.needs_follow_up = ev["needs_follow_up"]


def _follow_up_question(row: SessionAnswer, role_title: str, text: str) -> str | None:
    """The template's follow-up if it has one, otherwise one written by the provider."""
    if row.follow_up_question:
        return row.follow_up_question
    q, _ = run_json_task(
        follow_up_prompt(role_title, row.skill.name if row.skill else "General", row.question, text), LLMFollowUp,
        task="follow_up",
    )
    return q.question


# ---------- answer / follow-up / finish ----------

def _load(db: Session, interview_id: str) -> InterviewSession | None:
    return db.scalars(
        select(InterviewSession).where(InterviewSession.id == interview_id).options(
            selectinload(InterviewSession.answers).selectinload(SessionAnswer.skill), selectinload(InterviewSession.role)
        )
    ).first()


def _own(db: Session, user: User, interview_id: str) -> InterviewSession:
    session = _load(db, interview_id)
    if session is None or session.candidate_id != user.id:  # 404 either way: don't reveal other people's ids
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Interview not found.")
    return session


def _open_session(db: Session, user: User, interview_id: str) -> InterviewSession:
    session = _own(db, user, interview_id)
    if session.status != "in_progress":
        raise HTTPException(status.HTTP_409_CONFLICT, detail="This interview is already finished.")
    return session


def own_open(db: Session, user: User, interview_id: str) -> InterviewSession:
    """For routers: 404 if it isn't the candidate's, 409 if it's finished."""
    return _open_session(db, user, interview_id)


def _role_title(session: InterviewSession) -> str:
    return session.role.title if session.role else "this"


def _result(row: SessionAnswer, session: InterviewSession) -> dict:
    return {
        "answerId": row.id, "score": row.score, "criteria": row.criteria, "tips": row.tips or [],
        "provider": row.provider, "needsFollowUp": row.needs_follow_up, "answerSource": row.answer_source,
        "followUp": {"question": row.follow_up_question} if row.needs_follow_up else None,
        "answered": sum(1 for a in session.answers if a.answered_at is not None), "total": len(session.answers),
    }


def answer(db: Session, user: User, interview_id: str, body: AnswerBody, source: str | None = None) -> dict:
    """The one evaluation pipeline: text, voice and video answers all arrive here as text."""
    session = _open_session(db, user, interview_id)
    row = next((a for a in session.answers if body.question_id in (a.id, a.question_id)), None)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="That question isn't part of this interview.")
    if row.answered_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="You've already answered this question.")

    ev = _evaluate(db, _rules(db), _role_title(session), row, body.answer)
    row.answer, row.indicators, row.answered_at = body.answer, body.indicators, _now()
    row.answer_source = source or body.source or ("video" if body.indicators else "text")
    _store_evaluation(row, ev)
    if row.needs_follow_up:
        row.follow_up_question = _follow_up_question(row, _role_title(session), body.answer)
    db.commit()
    return _result(row, session)


def follow_up(db: Session, user: User, interview_id: str, answer_id: str, body: FollowUpBody) -> dict:
    session = _open_session(db, user, interview_id)
    row = next((a for a in session.answers if a.id == answer_id), None)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="That answer isn't part of this interview.")
    if row.answered_at is None or not row.needs_follow_up or row.follow_up is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="There is no follow-up to answer for this question.")

    before = row.score
    ev = _evaluate(db, _rules(db), _role_title(session), row, f"{row.answer}\n\n{body.answer}")
    _store_evaluation(row, ev)
    row.needs_follow_up = False
    row.follow_up = {"question": row.follow_up_question, "answer": body.answer, "before": before}
    row.indicators = body.indicators or row.indicators
    db.commit()
    return _result(row, session)


def finish(db: Session, user: User, interview_id: str) -> dict:
    session = _own(db, user, interview_id)
    if session.status == "completed":  # finishing twice just returns the same summary
        return summary(db, session)
    answered = [a for a in session.answers if a.answered_at is not None]
    if not answered:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Answer at least one question before finishing.")
    for a in [a for a in session.answers if a.answered_at is None]:
        session.answers.remove(a)  # skipped questions are dropped
    session.score = average([a.score for a in answered])
    session.status = "completed"
    db.commit()
    return summary(db, session)


# ---------- output ----------

def _answer_out(a: SessionAnswer) -> dict:
    return {
        "id": a.id, "templateId": a.question_id, "question": a.question, "skill": a.skill.name if a.skill else "",
        "type": a.type, "reason": a.reason, "answered": a.answered_at is not None, "answer": a.answer,
        "score": a.score, "criteria": a.criteria or {}, "tips": a.tips or [], "provider": a.provider,
        "needsFollowUp": a.needs_follow_up, "followUp": a.follow_up or None,
        "followUpQuestion": a.follow_up_question if a.needs_follow_up else None, "indicators": a.indicators,
        "answerSource": a.answer_source,
    }


def interview_out(s: InterviewSession) -> dict:
    return {
        "id": s.id, "status": s.status, "mode": s.mode, "roleId": s.role_id, "roleTitle": s.role.title if s.role else "",
        "jobId": s.job_id, "score": s.score, "date": to_ms(s.date),
        "questions": [_answer_out(a) for a in s.answers],
    }


def summary(db: Session, s: InterviewSession) -> dict:
    rules = _rules(db)
    tips = {t.name: t.tip for t in db.scalars(select(Skill))}
    by_skill = sorted(({"skill": a.skill.name, "score": a.score} for a in s.answers if a.skill), key=lambda x: x["score"])
    return {
        **interview_out(s),
        "summary": {
            "score": s.score, "answered": len(s.answers), "skills": by_skill,
            "focus": [{"skill": x["skill"], "score": x["score"], "tip": tips.get(x["skill"], "")}
                      for x in by_skill if x["score"] < rules["weakThreshold"]],
            "providers": sorted({a.provider for a in s.answers if a.provider}),
        },
    }


def list_interviews(db: Session, user: User) -> list[dict]:
    sessions = db.scalars(
        select(InterviewSession).where(InterviewSession.candidate_id == user.id)
        .options(selectinload(InterviewSession.answers), selectinload(InterviewSession.role))
        .order_by(InterviewSession.date.desc())
    )
    return [
        {"id": s.id, "status": s.status, "mode": s.mode, "roleId": s.role_id, "roleTitle": s.role.title if s.role else "",
         "jobId": s.job_id, "score": s.score, "date": to_ms(s.date), "questionCount": len(s.answers),
         "answeredCount": sum(1 for a in s.answers if a.answered_at is not None)}
        for s in sessions
    ]


def get_interview(db: Session, user: User, interview_id: str) -> dict:
    return interview_out(_own(db, user, interview_id))


# ---------- progress ----------

def progress(db: Session, user: User) -> dict:
    rules = _rules(db)
    sessions = _history(db, user.id)
    perf = skill_performance(_as_perf_input(sessions), rules)
    tips = {s.name: s.tip for s in db.scalars(select(Skill))}
    skills = [{**p, "tip": tips.get(p["skill"], "")} for p in perf]
    return {
        "sessionsCompleted": len(sessions),
        "averageScore": average([s.score for s in sessions]),
        "weakThreshold": rules["weakThreshold"], "weakMinSessions": rules["weakMinSessions"],
        "skills": skills,
        "scoreTrend": [{"sessionId": s.id, "date": to_ms(s.date), "score": s.score, "roleTitle": s.role.title if s.role else ""}
                       for s in sessions],
        "weaknessProfile": [{"skill": p["skill"], "avg": p["avg"], "sessions": p["sessions"], "trend": p["trend"], "tip": p["tip"]}
                            for p in skills if p["weak"]],
    }
