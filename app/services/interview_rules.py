"""Rule-based answer evaluation: a port of `evaluateAnswer` in the frontend's src/lib.js.

Used when Gemini is unavailable. It returns the same raw per-criterion scores (0-100) the
Gemini rubric returns; the overall score is always calculated by the caller."""

import math
import re

STAR_CUES = {
    "situation": ["when i", "during", "situation", "at my", "in my", "project", "while", "last year", "semester"],
    "task": ["needed to", "had to", "my role", "responsible", "goal", "task", "challenge", "asked to"],
    "action": ["i decided", "i created", "i built", "i spoke", "i started", "so i", "i used", "i worked", "i organised",
               "i organized", "i suggested", "i wrote", "i set up", "i proposed"],
    "result": ["as a result", "result", "outcome", "improved", "reduced", "increased", "learned", "finally", "which led",
              "in the end"],
}
FILLERS = ["um", "uh", "like", "basically", "actually", "you know", "kind of", "sort of", "literally"]
EXAMPLE = re.compile(r"\b(for example|for instance|e\.g\.|such as|in my|when i)\b")


def _round(x: float) -> int:  # JavaScript Math.round
    return math.floor(x + 0.5)


def _clamp(n: float, lo: float, hi: float) -> int:
    return int(min(hi, max(lo, n)))


def word_count(text: str) -> int:
    return len(text.split())


def star_parts(text: str) -> list[str]:
    lower = f" {text.lower()} "
    return [part for part, cues in STAR_CUES.items() if any(c in lower for c in cues)]


def evaluate(answer: str, question: dict, aliases: list[str], follow_up_below: int) -> dict:
    """question: {"text", "keywords", "skill", "type"}. Returns raw criteria, tips and needs_follow_up."""
    text = answer.strip()
    lower = f" {text.lower()} "
    words = word_count(text)
    tokens = re.findall(r"[a-z']+", lower)
    sentences = [s for s in (x.strip() for x in re.split(r"[.!?]+", text)) if s]
    avg_sentence = words / len(sentences) if sentences else words

    keywords = question.get("keywords") or []
    key_hits = [k for k in keywords if k.lower() in lower]
    q_terms = re.findall(r"[a-z]{5,}", question["text"].lower())
    rel_hits = sum(1 for t in dict.fromkeys([*(a.lower() for a in aliases), *q_terms]) if t in lower)
    has_example = bool(EXAMPLE.search(lower))
    filler_count = sum(len(re.findall(rf"\b{re.escape(f)}\b", lower)) for f in FILLERS)
    variety = len(set(tokens)) / len(tokens) if tokens else 0
    parts = star_parts(text)

    raw = {
        "technical": _clamp(_round(30 + (len(key_hits) / len(keywords) if keywords else 0.4) * 62 + (6 if has_example else 0)), 25, 97),
        "relevance": _clamp(42 + rel_hits * 11 + (8 if has_example else 0), 30, 96),
        "completeness": _clamp(_round(28 + min(words, 170) * 0.4 + (6 if has_example else 0)), 22, 96),
        "clarity": _clamp(_round(93 - abs(avg_sentence - 17) * 2.2), 35, 95),
        "communication": _clamp(_round(55 + variety * 45 - filler_count * 6 + (6 if words > 40 else 0)), 30, 95),
        "star": _clamp(32 + len(parts) * 16, 32, 96),
    }

    tips = []
    if question["type"] == "technical" and raw["technical"] < 60:
        missing = [k for k in keywords if k not in key_hits][:4]
        if missing:
            tips.append(f"Cover the key points: {', '.join(missing)}.")
    if raw["completeness"] < 60:
        tips.append("Add a concrete example from a project and say what the outcome was.")
    if raw["relevance"] < 60:
        tips.append(f"Tie the answer back to {question['skill'].lower()} more directly.")
    if raw["clarity"] < 60:
        tips.append("Use shorter sentences so each point lands clearly.")
    if filler_count > 1:
        tips.append(f"Cut filler words (found {filler_count}).")
    if question["type"] == "behavioral" and len(parts) < 4:
        gone = [p for p in ("situation", "task", "action", "result") if p not in parts]
        tips.append(f"Missing STAR parts: {', '.join(gone)}.")
    if not tips:
        tips.append("Strong answer. Next time, quantify the result if you can.")

    needs_follow_up = raw["completeness"] < follow_up_below or (question["type"] == "technical" and raw["technical"] < 50)
    return {**raw, "tips": tips[:3], "needs_follow_up": needs_follow_up}


def generic_question(skill: str, role_title: str, qtype: str) -> dict:
    """Offline stand-in when Gemini can't write a question for a skill that has no template."""
    if qtype == "behavioral":
        text = f"Tell me about a time you used {skill} to get something done in a team. What was the situation, what did you do and what was the result?"
        follow_up = "What would you do differently if you faced the same situation again?"
    else:
        text = f"Explain how you would use {skill} in a {role_title} role. Describe a concrete example of what you built or solved with it."
        follow_up = f"What is the hardest problem you have had with {skill}, and how did you solve it?"
    return {"text": text, "keywords": [skill.lower()], "follow_up": follow_up}


GENERIC_FOLLOW_UP = "Can you give a specific example from a project or study where you did this, and what the outcome was?"
