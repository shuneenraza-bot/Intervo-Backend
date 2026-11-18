"""CV skill matching, shared by the candidate's gap analysis, the interview engine and the
employer's candidate list. Employers only ever get the CV match (`cv_fit`); interview
scores never leave the candidate side.

Everything here is pure: plain dicts in, plain dicts out, in the JSON shape API.md documents.
`match_skills`, `skill_performance` and `js_round` are ports of the frontend's src/lib.js.
"""

from __future__ import annotations

import math
from typing import Any

# Used for any key missing from the scoring_rules row; same values as the frontend's data.js.
DEFAULT_RULES: dict[str, Any] = {
    "weakThreshold": 60,
    "weakMinSessions": 2,
}


def js_round(x: float) -> int:
    """JavaScript's Math.round: halves round up (Python's round() rounds them to even)."""
    return math.floor(x + 0.5)


def average(values: list[float]) -> int:
    return js_round(sum(values) / len(values)) if values else 0


def match_skills(candidate_skills: list[str], required: list[dict], skill_config: list[dict]) -> dict:
    """Weighted CV-job match. A required skill is "partial" when the candidate has one of its
    related skills; partial skills earn half their weight."""
    have = set(candidate_skills or [])
    related = {s["name"]: s.get("related") or [] for s in skill_config}
    matched, partial, missing = [], [], []
    for req in required:
        if req["name"] in have:
            matched.append(req)
            continue
        via = next((r for r in related.get(req["name"], []) if r in have), None)
        if via:
            partial.append({**req, "via": via})
        else:
            missing.append(req)
    total = sum(r["weight"] for r in required)
    got = sum(r["weight"] for r in matched) + sum(r["weight"] * 0.5 for r in partial)
    return {
        "matched": matched,
        "partial": partial,
        "missing": missing,
        "percentage": js_round(got / total * 100) if total else 0,
    }


def skill_performance(sessions: list[dict], rules: dict) -> list[dict]:
    """Per-skill history across sessions (oldest to newest), weakest skill first. A skill is a
    persistent weakness when it appears in at least `weakMinSessions` sessions and its average
    stays below `weakThreshold`."""
    history: dict[str, dict] = {}
    for session in sorted(sessions, key=lambda s: s["date"]):
        for answer in session["answers"]:
            entry = history.setdefault(answer["skill"], {"scores": [], "session_ids": set()})
            entry["scores"].append(answer["score"])
            entry["session_ids"].add(session["id"])

    result = []
    for skill, entry in history.items():
        scores = entry["scores"]
        avg = average(scores)
        count = len(entry["session_ids"])
        result.append({
            "skill": skill,
            "scores": scores,
            "avg": avg,
            "sessions": count,
            "latest": scores[-1],
            "trend": scores[-1] - scores[0] if len(scores) > 1 else 0,
            "weak": count >= rules["weakMinSessions"] and avg < rules["weakThreshold"],
        })
    return sorted(result, key=lambda p: p["avg"])


def cv_fit(job: dict, profile: dict | None, skill_config: list[dict], checks: list[dict] | None = None) -> dict:
    """What an employer sees about one applicant: the weighted CV skill match (matched /
    partial / missing with weights, percentage), the requirement checks and whether the
    job's minimum CV match is met. Nothing from interviews or practice goes in here."""
    cv = match_skills((profile or {}).get("skills") or [], job["skills"], skill_config)
    min_match = (job.get("success") or {}).get("minMatch") or 0
    return {**cv, "checks": checks or [], "meetsCriteria": cv["percentage"] >= min_match}


def cv_summary(cv: dict | None) -> dict | None:
    """The only CV details an employer sees: top degree, years of experience, project count."""
    if not cv:
        return None
    education = cv.get("education") or []
    return {
        "topDegree": (education[0].get("degree") or None) if education else None,
        "experienceYears": cv.get("experienceYears") or 0,
        "projectCount": len(cv.get("projects") or []),
    }
