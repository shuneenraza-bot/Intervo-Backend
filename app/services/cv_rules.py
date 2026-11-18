"""Deterministic CV / job-description logic, ported from the frontend's src/cvParser.js and
src/lib.js (extractSkills, matchSkills). Used by the RuleBased provider and, for
matching, always (matching is never AI)."""

from __future__ import annotations

import math
import re
from datetime import datetime

# ---------- helpers ----------

HEADINGS = {
    "summary": ["summary", "profile", "objective", "about me", "career objective", "professional summary", "personal statement"],
    "education": ["education", "academic", "academics", "academic background", "academic qualifications", "qualifications", "educational background"],
    "experience": ["experience", "work experience", "professional experience", "employment", "employment history", "work history", "internship", "internships", "internship experience"],
    "projects": ["projects", "academic projects", "personal projects", "key projects", "final year project", "project experience", "selected projects"],
    "skills": ["skills", "technical skills", "core skills", "key skills", "skills summary", "competencies", "core competencies", "tools", "technologies", "tools and technologies", "soft skills", "expertise"],
    "certifications": ["certifications", "certificates", "courses", "training", "achievements", "awards", "honors", "certifications and courses"],
    "other": ["languages", "interests", "hobbies", "references", "contact", "personal information", "personal details", "extracurricular activities", "activities", "volunteering"],
}

BULLET = re.compile(r"^[•●▪■◦‣\-–*·>✓]\s*")
MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
DATE = rf"(?:{MONTH}\s*,?\s*)?(?:\d{{1,2}}[/.-])?(?:19|20)\d{{2}}"
DATE_RANGE = re.compile(rf"({DATE})\s*(?:-|–|—|to|till|until)\s*({DATE}|present|current|now|ongoing|date)", re.I)
SINGLE_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
DEGREE = re.compile(
    r"\b(ph\.?d|doctorate|master'?s?|m\.?s\.?c?|m\.?phil|mba|bachelor'?s?|b\.?s\.?c?|b\.?e|b\.?tech|bs|bsc|bba|bcs|be|"
    r"intermediate|f\.?sc|fsc|ics|i\.?com|a[- ]levels?|o[- ]levels?|matric(?:ulation)?|ssc|hssc|diploma|associate degree)\b",
    re.I,
)
SCORE_LINE = re.compile(r"(?:c?gpa|percentage|grade|marks)\b", re.I)
INSTITUTE = re.compile(r"\b(university|college|institute|school|academy|campus|polytechnic|board)\b", re.I)
_MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PK_PHONE_RE = re.compile(r"(?:\+92[\s-]?|0)3\d{2}[\s-]?\d{7}")
ANY_PHONE_RE = re.compile(r"\+?\d[\d\s()-]{8,15}\d")


def _js_round(x: float) -> int:
    return math.floor(x + 0.5)


def extract_skills(text: str, skills: list[dict]) -> list[str]:
    """Library skills mentioned in free text (name or alias, whole-word)."""
    lower = f" {(text or '').lower()} "
    found = []
    for s in skills:
        terms = [s["name"].lower(), *[a.lower() for a in (s.get("aliases") or [])]]
        if any(re.search(rf"(^|[^a-z0-9]){re.escape(t)}([^a-z0-9]|$)", lower) for t in terms):
            found.append(s["name"])
    return found


def skill_lookup(skills: list[dict]) -> dict[str, str]:
    """lower-cased name or alias -> canonical skill name."""
    out: dict[str, str] = {}
    for s in skills:
        for term in [s["name"], *(s.get("aliases") or [])]:
            out.setdefault(term.lower().strip(), s["name"])
    return out


def heading_of(line: str) -> str | None:
    clean = re.sub(r"[:•|_\-–—#*]+", " ", line.lower())
    clean = re.sub(r"\s+", " ", clean).strip()
    if not clean or len(clean) > 38 or re.search(r"\d{3,}|@", clean):
        return None
    for key, words in HEADINGS.items():
        for w in words:
            if clean == w or (clean.startswith(w + " ") and len(clean.split(" ")) <= 4):
                return key
    return None


def _sentence_like(line: str) -> bool:
    return bool(re.search(r"[.;]$", line)) and len(line) > 40 and not DATE_RANGE.search(line)


def split_entries(lines: list[str]) -> list[dict]:
    """Splits a section into entries: header lines followed by bullet points."""
    entries: list[dict] = []
    cur: dict | None = None

    def close():
        nonlocal cur
        if cur and (cur["head"] or cur["bullets"]):
            entries.append(cur)
        cur = None

    for raw in lines:
        if not raw.strip():
            close()
            continue
        is_bullet = bool(BULLET.match(raw))
        line = BULLET.sub("", raw, count=1).strip()
        if not line:
            continue
        if is_bullet:
            cur = cur or {"head": [], "bullets": []}
            cur["bullets"].append(line)
        else:
            # A GPA / percentage line belongs to the entry above it (small improvement over cvParser.js).
            looks_like_detail = _sentence_like(line) or bool(SCORE_LINE.match(line))
            if cur and not looks_like_detail and (
                cur["bullets"]
                or len(cur["head"]) >= 3
                or (DATE_RANGE.search(line) and any(DATE_RANGE.search(h) for h in cur["head"]))
            ):
                close()
            cur = cur or {"head": [], "bullets": []}
            # Sentence-like lines after a header are descriptions, not headers.
            if len(cur["head"]) >= 1 and (len(line) > 90 or _sentence_like(line)):
                cur["bullets"].append(line)
            else:
                cur["head"].append(line)
    close()
    return entries


def strip_dates(s: str) -> str:
    s = DATE_RANGE.sub("", s)
    s = re.sub(r"\(\s*\)|\|\s*$|,\s*$|-\s*$|–\s*$", "", s)
    return re.sub(r"\s{2,}", " ", s).strip()


def find_dates(text: str) -> str:
    m = DATE_RANGE.search(text)
    if m:
        return re.sub(r"\s+", " ", m.group(0)).strip()
    y = SINGLE_YEAR.search(text)
    return y.group(0) if y else ""


def months_between(date_range: str) -> int:
    m = DATE_RANGE.search(date_range or "")
    if not m:
        return 0

    def to_date(s: str) -> datetime:
        if re.search(r"present|current|now|ongoing|date", s, re.I):
            return datetime.now()
        year = int(re.search(r"(?:19|20)\d{2}", s).group(0))
        mm = re.search(MONTH, s, re.I)
        month = _MONTHS.index(mm.group(0)[:3].lower()) if mm else 0
        return datetime(year, month + 1, 1)

    diff = (to_date(m.group(2)) - to_date(m.group(1))).days / 30.4
    return max(0, _js_round(diff))


def education_level(s: str = "") -> int:
    """Simple education level for comparing a CV against a JD requirement."""
    if re.search(r"ph\.?d|doctorate", s, re.I):
        return 4
    if re.search(r"master|\bms\b|m\.?sc|m\.?phil|mba", s, re.I):
        return 3
    if re.search(r"bachelor|\bbs\b|b\.?sc|\bbe\b|b\.?tech|bba|bcs", s, re.I):
        return 2
    if re.search(r"intermediate|f\.?sc|ics|a[- ]level|hssc|diploma", s, re.I):
        return 1
    return 0


# ---------- entries ----------

def _parse_education(entry: dict) -> dict:
    allv = [*entry["head"], *entry["bullets"]]
    text = " | ".join(allv)
    degree_line = next((l for l in allv if DEGREE.search(l)), None) or (entry["head"][0] if entry["head"] else "")
    inst = next((l for l in allv if INSTITUTE.search(l) and l != degree_line), None)
    if inst is None:
        inst = "" if INSTITUTE.search(degree_line) else next((l for l in entry["head"] if l != degree_line), "")
    gpa = re.search(r"\b(c?gpa)\s*[:\-]?\s*([\d.]+)\s*(?:/\s*([\d.]+))?", text, re.I)
    pct = re.search(r"\b(\d{2,3}(?:\.\d+)?)\s*%", text)
    if gpa:
        score = f"{gpa.group(1).upper()} {gpa.group(2)}" + (f" / {gpa.group(3)}" if gpa.group(3) else "")
    elif pct:
        score = f"{pct.group(1)}%"
    else:
        score = ""
    degree = re.split(r"\s+[|,–-]\s+(?=[A-Z][a-z]+ (?:University|College|Institute))", degree_line)[0]
    return {"degree": strip_dates(degree), "institution": strip_dates(inst), "dates": find_dates(text), "score": score}


def _parse_experience(entry: dict) -> dict:
    dates = find_dates(" ".join(entry["head"])) or find_dates(" ".join(entry["bullets"]))
    heads = [h for h in (strip_dates(h) for h in entry["head"]) if h]
    title = heads[0] if heads else ""
    company = heads[1] if len(heads) > 1 else ""
    if not company:
        parts = re.split(r"\s+(?:at|@)\s+|\s*[|,]\s*|\s+[–—-]\s+", title)
        if len(parts) > 1:
            title, company = parts[0], ", ".join(parts[1:])
    details = "\n".join(entry["bullets"]) or "\n".join(heads[2:])
    return {"title": title, "company": company, "dates": dates, "months": months_between(dates), "details": details}


def _parse_project(entry: dict, skills: list[dict]) -> dict:
    first = strip_dates((entry["head"][0] if entry["head"] else (entry["bullets"][0] if entry["bullets"] else "")))
    first = re.sub(r"^(project|fyp)\s*[:\-–]\s*", "", first, flags=re.I)
    pieces = re.split(r"\s+[|–—]\s+|:\s+", first) if len(first) > 70 else re.split(r"\s+\|\s+", first)
    name, rest = pieces[0], pieces[1:]
    details = "\n".join([*rest, *entry["head"][1:], *entry["bullets"]])
    return {"name": name.strip(), "tech": extract_skills(f"{first} {details}", skills), "details": details.strip()}


def parse_contact(header_lines: list[str], full_text: str) -> dict:
    email_m = EMAIL_RE.search(full_text)
    email = email_m.group(0) if email_m else ""
    phone_m = PK_PHONE_RE.search(full_text) or ANY_PHONE_RE.search(full_text)
    phone = phone_m.group(0).strip() if phone_m else ""
    li = re.search(r"linkedin\.com/in/[\w-]+", full_text, re.I)
    gh = re.search(r"github\.com/[\w-]+", full_text, re.I)

    def looks_like_name(l: str) -> bool:
        n = len(l.split())
        return not re.search(r"[@\d/]|http|www\.|linkedin|github", l, re.I) and 2 <= n <= 5 and len(l) < 40

    name = next((l for l in header_lines if looks_like_name(l)), header_lines[0] if header_lines else "")
    city = r"lahore|karachi|islamabad|rawalpindi|gujrat|faisalabad|multan|peshawar|quetta|sialkot"
    location = ""
    loc_line = next((l for l in header_lines if re.search(rf"({city}|pakistan)", l, re.I)), None)
    if loc_line:
        m = re.search(rf"[A-Za-z ]*({city})[A-Za-z ,]*(pakistan)?", loc_line, re.I)
        location = m.group(0).strip() if m else ""
    return {
        "name": re.sub(r"\s*[|,].*$", "", name).strip(),
        "email": email,
        "phone": phone,
        "linkedin": li.group(0) if li else "",
        "github": gh.group(0) if gh else "",
        "location": location,
    }


# ---------- CV ----------

def parse_cv(text: str, skills: list[dict]) -> dict:
    """Port of parseCV. Returns the structured fields (without contact details and warnings)."""
    sections: dict[str, list[str]] = {"header": []}
    current = "header"
    for line in text.split("\n"):
        h = heading_of(line)
        if h:
            current = h
            sections.setdefault(h, [])
            continue
        sections.setdefault(current, []).append(line)

    lib = extract_skills(text, skills)
    known = set(skill_lookup(skills))
    other: list[str] = []
    for l in sections.get("skills", []):
        l = BULLET.sub("", l, count=1)
        l = re.sub(r"^[^:]{2,25}:\s*", "", l)
        for piece in re.split(r"[,|;•/]| and ", l):
            s = piece.strip().rstrip(".").strip()
            if 2 <= len(s) <= 28 and len(s.split(" ")) <= 3 and s.lower() not in known and s not in other:
                other.append(s)

    education = [e for e in (_parse_education(x) for x in split_entries(sections.get("education", []))) if e["degree"] or e["institution"]]
    experience = [e for e in (_parse_experience(x) for x in split_entries(sections.get("experience", []))) if e["title"]]
    projects = [p for p in (_parse_project(x, skills) for x in split_entries(sections.get("projects", []))) if p["name"]]
    summary = " ".join(l for l in sections.get("summary", []) if l)[:600]
    certs = [c for c in (BULLET.sub("", l, count=1).strip() for l in sections.get("certifications", [])) if c][:10]
    return {
        "header": [l for l in sections["header"] if l.strip()][:8],
        "summary": summary,
        "skills": lib,
        "other_skills": other[:16],
        "education": education,
        "experience": experience,
        "projects": projects,
        "certifications": certs,
    }


def years_from_months(experience: list[dict]) -> float:
    total = sum(int(e.get("months") or 0) for e in experience)
    return _js_round(total / 12 * 2) / 2


# ---------- job description ----------

def parse_jd(text: str, skills: list[dict], role_skills: list[dict] | None = None) -> dict:
    role_skills = role_skills or []
    lines = re.split(r"\n|(?<=\.)\s+", text)
    out = []
    for name in extract_skills(text, skills):
        cfg = [s for s in skills if s["name"] == name]
        line_for = " ".join(l for l in lines if name in extract_skills(l, cfg)).lower()
        weight = next((s["weight"] for s in role_skills if s["name"] == name), 2)
        if re.search(r"must|required|requirement|strong|essential|proficien|expert|solid", line_for):
            weight = 3
        elif re.search(r"nice to have|preferred|plus|bonus|familiar|desirable|good to have", line_for):
            weight = 1
        out.append({"name": name, "weight": weight})
    years = re.search(r"(\d+)\s*\+?\s*(?:-\s*\d+\s*)?(?:years?|yrs?)", text, re.I)
    degree = re.search(r"\b(bachelor'?s?|master'?s?|bs|ms|bsc|msc|mba|bba|ph\.?d)\b[^.\n]{0,60}", text, re.I)
    title = next((l.strip() for l in text.split("\n") if l.strip() and len(l.strip()) < 70 and not l.strip().endswith(":")), "")
    return {
        "title": title,
        "skills": out,
        "min_years": int(years.group(1)) if years else 0,
        "education": re.sub(r"[,;]$", "", degree.group(0).strip()) if degree else "",
        "fresher_friendly": bool(re.search(r"fresh|graduate|intern|entry[- ]level|0\s*-\s*1 years?", text, re.I)),
    }


# ---------- matching ----------

def requirement_checks(jd: dict, experience_years: float, degrees: list[str]) -> list[dict]:
    """Experience and education checks of a CV against a parsed job description
    (`min_years`, `education`, `fresher_friendly`). Only requirements the JD states are checked."""
    checks = []
    if jd.get("min_years", 0) > 0:
        checks.append({
            "key": "experience", "label": "Experience",
            "required": f"{jd['min_years']}+ years", "actual": f"{experience_years:g} years",
            "met": experience_years >= jd["min_years"] or bool(jd.get("fresher_friendly")),
        })
    if jd.get("education"):
        need = education_level(jd["education"])
        levels = [(education_level(d), d) for d in degrees if d]
        have = max((lvl for lvl, _ in levels), default=0)
        checks.append({
            "key": "education", "label": "Education", "required": jd["education"],
            "actual": next((d for lvl, d in levels if lvl == have), "Not found"),
            "met": need == 0 or have >= need,
        })
    return checks


def match_skills(candidate_skills: list[str], required: list[dict], skills: list[dict]) -> dict:
    """Port of matchSkills: weighted match; a related skill earns half the weight ("partial")."""
    have = set(candidate_skills)
    matched, partial, missing = [], [], []
    for req in required:
        if req["name"] in have:
            matched.append(req)
            continue
        cfg = next((s for s in skills if s["name"] == req["name"]), None)
        via = next((r for r in (cfg or {}).get("related", []) if r in have), None)
        if via:
            partial.append({**req, "via": via})
        else:
            missing.append(req)
    total = sum(r["weight"] for r in required)
    got = sum(r["weight"] for r in matched) + sum(r["weight"] * 0.5 for r in partial)
    return {"matched": matched, "partial": partial, "missing": missing,
            "percentage": _js_round(got / total * 100) if total else 0}
