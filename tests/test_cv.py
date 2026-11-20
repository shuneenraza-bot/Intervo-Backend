"""CV upload and analysis, JD parsing and matching. Tests use the rule-based provider only:
no network, no API key."""

import io
import zipfile
from pathlib import Path

import pytest
from docx import Document
from pypdf import PdfWriter

from app.config import settings
from app.models import CandidateProfile, Domain, JobRole, RoleSkill, Skill
from app.services import ai
from app.services.ai.base import AIUnavailable, InvalidAIResponse, LLMProvider
from app.services.ai.prompts import strip_contact
from app.services.cv_text import MAX_FILE_BYTES
from tests.conftest import employer_payload, signup_full

SAMPLE = Path(__file__).parent.parent / "docs" / "sample-cv.txt"
SKILLS = {  # name -> (aliases, related)
    "React": (["reactjs", "react.js"], ["JavaScript"]),
    "JavaScript": (["js", "es6"], ["TypeScript", "React"]),
    "TypeScript": (["ts"], ["JavaScript"]),
    "HTML": ([], ["CSS"]),
    "CSS": (["css3"], ["HTML"]),
    "Git": ([], []),
    "Node.js": (["node", "nodejs"], ["JavaScript"]),
    "Testing": (["jest", "unit testing"], []),
    "Communication": ([], ["Teamwork"]),
    "Teamwork": ([], ["Communication"]),
    "Python": (["py"], []),
}


def skill_id(name: str) -> str:
    return name.lower().replace(".", "")


@pytest.fixture(autouse=True)
def rules_only(monkeypatch):
    monkeypatch.setattr(settings, "ai_provider", "rules")


@pytest.fixture
def library(db):
    db.add(Domain(id="web", name="Web"))
    for name, (aliases, related) in SKILLS.items():
        db.add(Skill(id=skill_id(name), name=name, aliases=aliases, related=related))
    db.flush()
    db.add(JobRole(id="frontend", domain_id="web", title="Frontend Developer"))
    db.flush()
    for name, weight in [("React", 3), ("JavaScript", 3), ("CSS", 2), ("Python", 1)]:
        db.add(RoleSkill(role_id="frontend", skill_id=skill_id(name), weight=weight))
    db.commit()


@pytest.fixture
def auth(candidate):
    return {"Authorization": f"Bearer {candidate['token']}"}


def upload(client, auth, name="cv.txt", data=None, ctype="text/plain"):
    data = SAMPLE.read_bytes() if data is None else data
    return client.post("/api/cv", headers=auth, files={"file": (name, data, ctype)})


def make_docx(lines: list[str]) -> bytes:
    doc = Document()
    for line in lines:
        doc.add_paragraph(line)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def make_pdf(text: str) -> bytes:
    """A one-page PDF with real selectable text, written by hand."""
    shown = " ".join(f"({line.replace('(', '[').replace(')', ']')}) '" for line in text.split("\n"))
    stream = f"BT /F1 11 Tf 40 800 Td 14 TL {shown} ET"
    objs = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out, offsets = b"%PDF-1.4\n", []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{body}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    return out


# ---------- upload & parsing ----------

def test_txt_upload_parses_and_saves(client, auth, library, db, candidate):
    res = upload(client, auth)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["provider"] == "rules" and body["fileName"] == "cv.txt"
    cv = body["cv"]
    assert cv["contact"]["name"] == "Ayesha Khan"
    assert cv["contact"]["email"] == "ayesha.khan@example.com"
    assert cv["contact"]["phone"].replace(" ", "") == "+923001234567"
    assert cv["contact"]["github"] == "github.com/ayeshakhan"
    assert {"React", "JavaScript", "TypeScript", "HTML", "CSS", "Git", "Testing", "Node.js"} <= set(cv["skills"])
    assert cv["education"][0]["degree"] == "BS Computer Science"
    assert cv["education"][0]["score"] == "CGPA 3.4 / 4.0"
    assert cv["experience"][0]["title"] == "Frontend Intern"
    assert cv["experience"][0]["months"] == 3 and cv["experienceYears"] == 0.5
    assert cv["projects"][0]["name"].startswith("Interview Practice App")
    assert {"React", "JavaScript", "Node.js"} <= set(cv["projects"][0]["tech"])
    assert cv["certifications"] == ["Meta Front-End Developer Certificate"]
    assert "skills" in cv["sectionsFound"]

    profile = db.get(CandidateProfile, candidate["user"]["id"])
    assert profile.cv_file_name == "cv.txt" and "Frontend Intern" in profile.cv_text
    assert profile.cv_provider == "rules"
    assert "React" in profile.skills
    assert profile.cv["experienceYears"] == 0.5  # the summary employers read


def test_docx_and_pdf_upload(client, auth, library):
    lines = SAMPLE.read_text(encoding="utf-8").split("\n")
    res = upload(client, auth, "cv.docx", make_docx(lines))
    assert res.status_code == 200, res.text
    assert "React" in res.json()["cv"]["skills"]
    res = upload(client, auth, "cv.pdf", make_pdf("\n".join(lines)), "application/pdf")
    assert res.status_code == 200, res.text
    assert "React" in res.json()["cv"]["skills"]


def test_scanned_pdf_is_rejected(client, auth, library):
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    buf = io.BytesIO()
    writer.write(buf)
    res = upload(client, auth, "scan.pdf", buf.getvalue(), "application/pdf")
    assert res.status_code == 422 and "scanned" in res.json()["detail"]


@pytest.mark.parametrize("name,data,status,fragment", [
    ("cv.exe", b"hello", 415, "PDF, DOCX or TXT"),
    ("cv.doc", b"hello", 422, ".docx"),
    ("cv.txt", b"", 422, "empty"),
    ("cv.txt", b"too short", 422, "readable text"),
    ("cv.pdf", b"not a pdf at all", 422, "not a valid PDF"),
    ("cv.docx", b"not a zip", 422, "not a valid DOCX"),
    ("cv.docx", b"PK\x03\x04garbage", 422, "not a valid DOCX"),
    ("cv.txt", b"a" * (MAX_FILE_BYTES + 1), 413, "5 MB"),
])
def test_bad_uploads(client, auth, library, name, data, status, fragment):
    res = upload(client, auth, name, data)
    assert res.status_code == status and fragment in res.json()["detail"]


def test_zip_bomb_docx_is_rejected(client, auth, library):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml", b"0" * (60 * 1024 * 1024))
    assert upload(client, auth, "bomb.docx", buf.getvalue()).status_code == 422


def test_cv_endpoints_are_candidate_only(client, library):
    headers = {"Authorization": f"Bearer {signup_full(client, employer_payload())['token']}"}
    assert upload(client, headers).status_code == 403
    assert client.get("/api/cv", headers=headers).status_code == 403
    assert client.post("/api/jd/parse", headers=headers, json={"text": "React"}).status_code == 403
    assert client.get("/api/cv").status_code == 401


# ---------- get / put ----------

def test_get_and_put_cv(client, auth, library, db, candidate):
    assert client.get("/api/cv", headers=auth).status_code == 404
    upload(client, auth)
    got = client.get("/api/cv", headers=auth).json()
    assert got["provider"] == "rules" and got["fileName"] == "cv.txt" and "Frontend Intern" in got["text"]

    edited = got["cv"]
    edited["skills"] = ["reactjs", "Git", "Rust"]  # alias, canonical, unknown
    edited["experienceYears"] = 2
    res = client.put("/api/cv", headers=auth, json=edited)
    assert res.status_code == 200, res.text
    cv = res.json()["cv"]
    assert cv["skills"] == ["React", "Git"] and "Rust" in cv["otherSkills"]
    assert cv["experienceYears"] == 2
    profile = db.get(CandidateProfile, candidate["user"]["id"])
    db.refresh(profile)
    assert profile.skills == ["React", "Git"] and profile.cv["experienceYears"] == 2
    assert profile.cv_text  # edits keep the extracted text
    assert client.put("/api/cv", headers=auth, json={"experienceYears": -1}).status_code == 422


def test_profile_sync_does_not_wipe_parsed_cv(client, auth, library, candidate):
    upload(client, auth)
    client.put("/api/profile", headers=auth, json={"skills": ["Git"], "cv": None, "shareWithEmployers": False})
    assert client.get("/api/cv", headers=auth).json()["cv"]["contact"]["name"] == "Ayesha Khan"


# ---------- JD ----------

JD = """Junior Frontend Developer
We are looking for a fresher or graduate to join us.
Requirements: strong React and JavaScript, 1+ years of experience.
Nice to have: Git, Python.
Bachelor's degree in Computer Science.
We also use CSS."""


def test_jd_parse(client, auth, library):
    res = client.post("/api/jd/parse", headers=auth, json={"text": JD})
    assert res.status_code == 200, res.text
    body = res.json()
    weights = {s["name"]: s["weight"] for s in body["skills"]}
    assert weights == {"React": 3, "JavaScript": 3, "Git": 1, "Python": 1, "CSS": 2}
    assert body["minYears"] == 1 and body["fresherFriendly"] is True
    assert body["education"].startswith("Bachelor's degree in Computer Science")
    assert body["title"] == "Junior Frontend Developer" and body["provider"] == "rules"


def test_jd_role_skills_set_default_weight(client, auth, library):
    res = client.post("/api/jd/parse", headers=auth, json={"text": "We use CSS.", "roleSkills": [{"name": "CSS", "weight": 3}]})
    assert res.json()["skills"] == [{"name": "CSS", "weight": 3}]
    assert client.post("/api/jd/parse", headers=auth, json={"text": ""}).status_code == 422


# ---------- match ----------

def test_match_role(client, auth, library):
    assert client.post("/api/cv/match", headers=auth, json={"roleId": "frontend"}).status_code == 404  # no CV yet
    upload(client, auth)
    cv = client.get("/api/cv", headers=auth).json()["cv"]
    client.put("/api/cv", headers=auth, json={**cv, "skills": ["JavaScript", "CSS"]})
    res = client.post("/api/cv/match", headers=auth, json={"roleId": "frontend"})
    assert res.status_code == 200, res.text
    body = res.json()
    # React (3) is partial via JavaScript = 1.5, JavaScript (3) + CSS (2) matched, Python (1) missing
    assert {s["name"] for s in body["matched"]} == {"JavaScript", "CSS"}
    assert body["partial"] == [{"name": "React", "weight": 3, "via": "JavaScript"}]
    assert [s["name"] for s in body["missing"]] == ["Python"]
    assert body["percentage"] == round((3 + 2 + 1.5) / 9 * 100) and body["checks"] == []
    assert client.post("/api/cv/match", headers=auth, json={"roleId": "nope"}).status_code == 404


def test_match_jd_with_checks(client, auth, library):
    upload(client, auth)
    text = JD.replace("fresher or graduate", "senior engineer").replace("1+", "3+")
    jd = client.post("/api/jd/parse", headers=auth, json={"text": text}).json()
    jd.pop("provider")
    res = client.post("/api/cv/match", headers=auth, json={"jd": jd})
    assert res.status_code == 200, res.text
    checks = {c["key"]: c for c in res.json()["checks"]}
    assert checks["experience"]["met"] is False and checks["experience"]["required"] == "3+ years"
    assert checks["education"]["met"] is True and checks["education"]["actual"] == "BS Computer Science"
    assert [s["name"] for s in res.json()["missing"]] == ["Python"]


def test_match_needs_exactly_one_target(client, auth, library):
    upload(client, auth)
    assert client.post("/api/cv/match", headers=auth, json={}).status_code == 422
    both = {"roleId": "frontend", "jd": {"skills": []}}
    assert client.post("/api/cv/match", headers=auth, json=both).status_code == 422


# ---------- provider layer ----------

class FakeProvider(LLMProvider):
    name = "gemini"

    def __init__(self, *responses):
        self.responses, self.prompts = list(responses), []

    def generate_json(self, prompt, schema, **context):
        self.prompts.append(prompt)
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


GOOD = {"summary": "Student.", "skills": ["reactjs", "Rust"], "other_skills": ["Public speaking"],
        "experience": [{"title": "Intern", "company": "Acme", "dates": "Jan 2024 - Jun 2024", "details": "", "months": None}],
        "projects": [{"name": "Shop", "details": "", "tech": ["js"]}]}


def use(monkeypatch, provider):
    monkeypatch.setattr(ai, "get_provider", lambda: provider)


def test_gemini_result_is_normalised(client, auth, library, monkeypatch):
    fake = FakeProvider(GOOD)
    use(monkeypatch, fake)
    body = upload(client, auth).json()
    cv = body["cv"]
    assert body["provider"] == "gemini" and len(fake.prompts) == 1
    assert "React" in cv["skills"] and "Rust" not in cv["skills"]  # alias -> library name, unknown -> other
    assert "Rust" in cv["otherSkills"] and "Public speaking" in cv["otherSkills"]
    assert cv["projects"][0]["tech"][0] == "JavaScript"
    assert cv["experience"][0]["months"] == 5 and cv["experienceYears"] == 0.5
    assert cv["contact"]["email"] == "ayesha.khan@example.com"  # from local rules, not the AI


def test_only_cleaned_text_is_sent_to_the_ai(client, auth, library, monkeypatch):
    fake = FakeProvider(GOOD)
    use(monkeypatch, fake)
    upload(client, auth)
    sent = fake.prompts[0]
    for private in ("ayesha.khan@example.com", "1234567", "linkedin.com", "github.com"):
        assert private not in sent
    assert "React" in sent and "Frontend Intern" in sent


def test_strip_contact():
    text = "Ali Raza\nEmail: ali@x.com\nCall +92 300 1234567 or ali@x.com now\nLahore | 0300-1234567\nSkills: Python"
    out = strip_contact(text)
    assert "@" not in out and "1234567" not in out and "Skills: Python" in out and "Ali Raza" in out


@pytest.mark.parametrize("failure", [AIUnavailable("quota"), RuntimeError("boom")])
def test_unavailable_gemini_falls_back_without_retry(client, auth, library, monkeypatch, failure):
    fake = FakeProvider(failure)
    use(monkeypatch, fake)
    res = upload(client, auth)
    assert res.status_code == 200 and res.json()["provider"] == "rules" and len(fake.prompts) == 1


def test_invalid_json_is_retried_once(client, auth, library, monkeypatch):
    fake = FakeProvider(InvalidAIResponse("not json"), GOOD)
    use(monkeypatch, fake)
    assert upload(client, auth).json()["provider"] == "gemini" and len(fake.prompts) == 2


def test_invalid_twice_falls_back(client, auth, library, monkeypatch):
    fake = FakeProvider({"skills": "not a list"}, InvalidAIResponse("nope"))
    use(monkeypatch, fake)
    res = upload(client, auth)
    assert res.json()["provider"] == "rules" and len(fake.prompts) == 2


def test_missing_key_uses_rules(monkeypatch):
    monkeypatch.setattr(settings, "ai_provider", "gemini")
    monkeypatch.setattr(settings, "gemini_api_key", None)
    assert ai.get_provider().name == "rules"
    monkeypatch.setattr(settings, "ai_provider", "rules")
    assert ai.get_provider().name == "rules"


def test_gemini_jd_is_normalised(client, auth, library, monkeypatch):
    fake = FakeProvider({"title": "Dev", "skills": [{"name": "ReactJS", "weight": 3}, {"name": "Cobol", "weight": 3}],
                         "min_years": 2, "education": "BS", "fresher_friendly": False})
    use(monkeypatch, fake)
    body = client.post("/api/jd/parse", headers=auth, json={"text": "We need ReactJS. Nice to have: Git."}).json()
    assert body["provider"] == "gemini" and body["minYears"] == 2
    assert {"name": "React", "weight": 3} in body["skills"] and {"name": "Git", "weight": 1} in body["skills"]
    assert all(s["name"] != "Cobol" for s in body["skills"])


def test_experience_years_are_computed_in_python_not_taken_from_gemini(client, auth, library, monkeypatch):
    lying = {**GOOD, "experienceYears": 0.5, "experience_years": 0.5, "experience": [
        {"title": "Developer", "company": "Acme", "dates": "Jan 2022 - Jan 2023", "details": "", "months": 1},
        {"title": "Engineer", "company": "Beta", "dates": "Feb 2023 - Feb 2024", "details": "", "months": 2},
    ]}
    use(monkeypatch, FakeProvider(lying))
    cv = upload(client, auth).json()["cv"]
    assert [e["months"] for e in cv["experience"]] == [12, 12]
    assert cv["experienceYears"] == 2


def test_present_means_today(monkeypatch):
    from datetime import datetime
    from app.services import cv_rules

    class Fixed(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 11, 15)

    monkeypatch.setattr(cv_rules, "datetime", Fixed)
    assert cv_rules.months_between("Nov 2024 - Present") == 24
    assert cv_rules.years_from_months([{"months": 24}]) == 2
