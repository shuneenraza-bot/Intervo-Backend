"""Employer-facing suitability score. A direct port of the frontend's src/lib.js
(`matchSkills`, `skillPerformance`, `suitability`), so both sides produce the same numbers.

Everything here is pure: plain dicts in, plain dicts out, in the JSON shape API.md documents.

    job      {"skills": [{"name", "weight"}], "success": {"minScore", "minMatch"}}
    profile  {"skills": [skill names]} or None
    sessions [{"id", "date", "score", "answers": [{"skill", "score"}]}]
    config   {"rules": {...}, "skills": [{"name", "related": [names]}]}
"""

from __future__ import annotations

import math
from typing import Any

# Used for any key missing from the scoring_rules row; same values as the frontend's data.js.
DEFAULT_RULES: dict[str, Any] = {
    "weakThreshold": 60,
    "weakMinSessions": 2,
    "suitability": {"cv": 40, "interview": 45, "consistency": 15},
}


def js_round(x: float) -> int:
    """JavaScript's Math.round: halves round up (Python's round() rounds them to even)."""
    return math.floor(x + 0.5)


def average(values: list[float]) -> int:
    return js_round(sum(values) / len(values)) if values else 0


def clamp(n: float, lo: float, hi: float) -> float:
    return min(hi, max(lo, n))


def plural(n: int, word: str) -> str:
    return f"{n} {word if n == 1 else word + 's'}"


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


def suitability(job: dict, profile: dict | None, sessions: list[dict], config: dict) -> dict:
    """Weighted suitability = CV skill match + interview evidence on the job's skills
    + practice consistency. Returns every factor so the employer sees why."""
    rules = {**DEFAULT_RULES, **(config.get("rules") or {})}
    w = {**DEFAULT_RULES["suitability"], **(rules.get("suitability") or {})}
    job_skills = job["skills"]
    success = job.get("success") or {}

    cv = match_skills((profile or {}).get("skills") or [], job_skills, config.get("skills") or [])
    perf = skill_performance(sessions, rules)
    perf_by_skill = {p["skill"]: p for p in perf}

    evidence = [
        {**js, "perf": perf_by_skill[js["name"]]} if js["name"] in perf_by_skill else {**js}
        for js in job_skills
    ]
    with_data = [e for e in evidence if "perf" in e]
    evidence_weight = sum(e["weight"] for e in with_data)
    interview = (
        js_round(sum(e["perf"]["avg"] * e["weight"] for e in with_data) / evidence_weight)
        if evidence_weight
        else 0
    )
    coverage = js_round(len(with_data) / len(job_skills) * 100) if job_skills else 0

    trend = average([p["trend"] for p in perf])
    consistency = int(clamp(js_round(40 + len(sessions) * 12 + trend), 0, 100)) if sessions else 0

    weight_sum = w["cv"] + w["interview"] + w["consistency"]
    total = (
        js_round((cv["percentage"] * w["cv"] + interview * w["interview"] + consistency * w["consistency"]) / weight_sum)
        if weight_sum
        else 0
    )
    avg_score = average([s["score"] for s in sessions])

    return {
        "total": total,
        "factors": [
            {
                "key": "cv", "label": "CV skill match", "value": cv["percentage"], "weight": w["cv"],
                "detail": f"{len(cv['matched'])} matched, {len(cv['partial'])} partial, {len(cv['missing'])} missing",
            },
            {
                "key": "interview", "label": "Interview evidence", "value": interview, "weight": w["interview"],
                "detail": (
                    f"Scored on {len(with_data)} of {len(job_skills)} required skills ({coverage}% coverage)"
                    if with_data
                    else "No interview answers on this job's skills yet"
                ),
            },
            {
                "key": "consistency", "label": "Practice consistency", "value": consistency, "weight": w["consistency"],
                "detail": f"{plural(len(sessions), 'session')}, average trend {'+' if trend >= 0 else ''}{trend}",
            },
        ],
        "cv": cv,
        "evidence": evidence,
        "avgScore": avg_score,
        "meetsCriteria": avg_score >= (success.get("minScore") or 0) and cv["percentage"] >= (success.get("minMatch") or 0),
        "weak": [p["skill"] for p in perf if p["weak"]],
    }


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
