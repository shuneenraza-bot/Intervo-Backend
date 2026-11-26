"""Gemini-written interview questions: what is sent, what is accepted.

The interview engine picks the slots (skill, type, difficulty) and a stored template as the
fallback for each. This module asks the provider for one new question per slot and returns None
for a slot whose call failed, timed out or produced something unacceptable.

Privacy: the prompt carries the role, its responsibilities, skill names from the library, the
CV's project names and technologies (contact data removed), key points the candidate missed and
earlier question texts. Never a name, email, phone, address or contact line."""

import difflib
import logging
import re
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass, field

from app.config import settings
from app.models import CandidateProfile, QuestionTemplate, Skill, User
from app.schemas.interview import LLMGeneratedQuestion
from app.services import ai
from app.services.ai.prompts import question_prompt, strip_contact

log = logging.getLogger("intervo.interview")

MAX_PROJECTS = 6
MAX_TECH = 8
# A vocabulary term shared by more skills than this ("example", "result") says nothing about the skill.
MAX_SKILLS_PER_TERM = 3


@dataclass
class CandidateContext:
    """The CV facts a question may be built on."""

    skills: list[str] = field(default_factory=list)
    projects: list[str] = field(default_factory=list)  # "Name (tech, tech)"


@dataclass
class Slot:
    skill: Skill
    type: str
    reason: str
    fallback: QuestionTemplate | None = None
    examples: list[str] = field(default_factory=list)  # stored question texts, as style examples
    missed: list[str] = field(default_factory=list)  # key points missed in earlier answers on this skill
    recent: list[str] = field(default_factory=list)  # this skill's questions in the last sessions (sent)
    known: list[str] = field(default_factory=list)  # question texts a new one must not repeat (checked here)

    @property
    def difficulty(self) -> str:
        return self.fallback.difficulty if self.fallback is not None else "medium"


# ---------- what is sent ----------

def private_values(user: User | None, profile: CandidateProfile | None) -> list[str]:
    """The candidate's name, address and profile handles: removed from every text that is sent."""
    contact = ((profile.parsed_cv or {}).get("contact") or {}) if profile is not None else {}
    values = [user.name if user is not None else ""]
    values += [contact.get(k) or "" for k in ("name", "email", "phone", "location", "linkedin", "github")]
    return [v for v in values if v]


def clean(text: str, private: list[str], limit: int) -> str:
    """One line without contact data, at most `limit` characters."""
    return " ".join(strip_contact(str(text or ""), private).split())[:limit].strip(" ,;:-|")


def candidate_context(user: User | None, profile: CandidateProfile | None, library: list[str]) -> CandidateContext:
    """CV skills (only names that are in the skill library) and project names with their technologies."""
    if profile is None:
        return CandidateContext()
    private = private_values(user, profile)
    known = set(library)
    cv = profile.parsed_cv or profile.cv or {}
    projects = []
    for p in (cv.get("projects") or [])[:MAX_PROJECTS]:
        name = clean(p.get("name"), private, 80)
        tech = [t for t in (clean(x, private, 40) for x in (p.get("tech") or [])[:MAX_TECH]) if t]
        if name or tech:
            projects.append(f"{name or 'Unnamed project'} ({', '.join(tech)})" if tech else name)
    return CandidateContext(skills=[s for s in (profile.skills or []) if s in known][:30], projects=projects)


# ---------- what is accepted ----------

def vocabulary(skills: list[Skill], templates: list[QuestionTemplate]) -> dict[str, set[str]]:
    """Per skill, the words that show a question is about it: its name, aliases and the key points
    of its stored templates."""
    points: dict[str, set[str]] = {}
    for t in templates:
        points.setdefault(t.skill_id, set()).update(k.strip().lower() for k in t.keywords or [] if k.strip())
    shared = Counter(term for terms in points.values() for term in terms)
    out = {}
    for s in skills:
        own = {s.name.lower(), *(a.strip().lower() for a in s.aliases or [] if a.strip())}
        out[s.id] = own | {t for t in points.get(s.id, set()) if shared[t] <= MAX_SKILLS_PER_TERM}
    return out


def mentions(text: str, terms: set[str]) -> bool:
    lower = text.lower()
    return any(re.search(rf"(?<![a-z0-9]){re.escape(t)}(?:s|es)?(?![a-z0-9])", lower) for t in terms)


def _normal(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", text.lower()).split())


def is_repeat(text: str, others: list[str]) -> bool:
    mine = _normal(text)
    return any(difflib.SequenceMatcher(None, mine, _normal(o)).ratio() >= 0.8 for o in others)


def reject_reason(q: LLMGeneratedQuestion, slot: Slot, terms: set[str], accepted: list[str]) -> str | None:
    if q.skill.strip().lower() != slot.skill.name.lower():
        return "off-skill (labelled with another skill)"
    if not mentions(" ".join([q.text, *q.keywords, q.follow_up]), terms):
        return "off-skill (nothing in it refers to the skill)"
    if is_repeat(q.text, [*slot.known, *accepted]):
        return "duplicate of an existing or recently asked question"
    return None


# ---------- the calls ----------

def generate(
    role_title: str, responsibilities: list[str], context: CandidateContext, slots: list[Slot],
    terms: dict[str, set[str]],
) -> list[LLMGeneratedQuestion | None]:
    """One question per slot, or None where the stored template must be used. The calls run in
    parallel under one deadline, so starting an interview never waits much longer than one call."""
    results: list[LLMGeneratedQuestion | None] = [None] * len(slots)
    provider = ai.get_provider()
    if provider.name == "rules" or not slots:
        return results

    def ask(slot: Slot) -> LLMGeneratedQuestion:
        prompt = question_prompt(
            role_title, responsibilities, slot.skill.name, slot.type, slot.difficulty,
            context.skills, context.projects, slot.missed, slot.examples, slot.recent,
        )
        return LLMGeneratedQuestion.model_validate(
            provider.generate_json(prompt, LLMGeneratedQuestion, task="question", skill=slot.skill.name,
                                   role=role_title, type=slot.type)
        )

    # Everything the threads read is loaded here: a SQLAlchemy object must not be lazy-loaded in a thread.
    for slot in slots:
        _ = (slot.skill.name, slot.difficulty)

    pool = ThreadPoolExecutor(max_workers=len(slots))
    started = time.monotonic()
    futures = [pool.submit(ask, slot) for slot in slots]
    wait(futures, timeout=settings.ai_timeout_seconds)
    pool.shutdown(wait=False, cancel_futures=True)

    accepted: list[str] = []
    for i, (slot, future) in enumerate(zip(slots, futures)):
        if not future.done():
            log.warning("question: %s timed out after %.0fs; using a stored template", slot.skill.name,
                        time.monotonic() - started)
            continue
        error = future.exception()
        if error is not None:  # the type only: a message could quote the model's output
            log.warning("question: %s failed (%s); using a stored template", slot.skill.name, type(error).__name__)
            continue
        q = future.result()
        why = reject_reason(q, slot, terms.get(slot.skill.id, {slot.skill.name.lower()}), accepted)
        if why:
            log.warning("question: %s rejected, %s; using a stored template", slot.skill.name, why)
            continue
        accepted.append(q.text)
        results[i] = q
    return results
