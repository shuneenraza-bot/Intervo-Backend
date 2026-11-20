"""Original CV files: storage, the CV needed to apply, the per-application snapshot and what
the job owner may read before and after the candidate accepts."""

from pathlib import Path

from app.models import Application, CvFile
from tests.conftest import candidate_payload
from tests.test_employer import (  # noqa: F401  (catalog is autouse)
    catalog, create_job, employer, other_employer, signup,
)
from tests.test_shortlist import apply, respond, shortlist

SAMPLE = Path(__file__).parent.parent / "docs" / "sample-cv.txt"
SECOND = (
    "Ayesha Khan\nayesha.khan@example.com | +92 300 1234567\n\nSUMMARY\nBackend engineer focused on Python APIs.\n\n"
    "EXPERIENCE\nBackend Developer, Acme Corp\n2022 - 2024\nBuilt Python services with Git and testing.\n\n"
    "SKILLS\nPython, Git, Testing, Communication\n"
)


def upload(client, headers, name="ayesha_cv.txt", data: bytes | None = None):
    data = SAMPLE.read_bytes() if data is None else data
    res = client.post("/api/cv", files={"file": (name, data, "text/plain")}, headers=headers)
    assert res.status_code == 200, res.text
    return res.json()


def stored(storage_dir):
    return sorted(p.name for p in storage_dir.glob("*")) if storage_dir.exists() else []


def cv_url(application, suffix="cv"):
    return f"/api/applications/{application['id']}/{suffix}"


def accepted_application(client, employer, headers, job):
    application = apply(client, job, headers)
    assert shortlist(client, application, employer[1]).status_code == 200
    assert respond(client, application, headers, "accept").status_code == 200
    return application


def candidate(client, name="Ayesha Khan", email="ayesha@example.com"):
    return signup(client, candidate_payload(name=name, email=email))


# ---------- storing and applying ----------

def test_apply_without_cv_is_400(client, employer):
    job = create_job(client, employer[1])
    _, headers = candidate(client)
    res = client.post(f"/api/jobs/{job['id']}/apply", json={"consent": True}, headers=headers)
    assert res.status_code == 400 and res.json()["detail"] == "Upload your CV before applying"
    assert client.get("/api/jobs", headers=headers).json()["applications"] == []


def test_upload_stores_the_file_under_a_random_name(client, db, storage_dir):
    user, headers = candidate(client)
    body = upload(client, headers)
    assert body["file"]["name"] == "ayesha_cv.txt" and body["file"]["size"] == len(SAMPLE.read_bytes())
    assert body["file"]["contentType"].startswith("text/plain") and body["file"]["uploadedAt"] > 0

    files = stored(storage_dir)
    assert len(files) == 1 and "ayesha" not in files[0] and files[0].endswith(".txt")
    assert (storage_dir / files[0]).read_bytes() == SAMPLE.read_bytes()
    row = db.query(CvFile).one()
    assert row.user_id == user["id"] and row.storage_name == files[0] and row.size_bytes == len(SAMPLE.read_bytes())
    assert files[0] not in str(body)


def test_new_upload_replaces_the_current_file(client, db, storage_dir):
    _, headers = candidate(client)
    upload(client, headers)
    second = upload(client, headers, "second.txt", SECOND.encode())
    assert len(stored(storage_dir)) == 1  # nothing applied with the first one, so it is gone
    assert db.query(CvFile).one().file_name == "second.txt"
    assert client.get("/api/cv", headers=headers).json()["file"]["name"] == second["file"]["name"] == "second.txt"


def test_rejected_upload_stores_nothing(client, storage_dir):
    _, headers = candidate(client)
    res = client.post("/api/cv", files={"file": ("evil.exe", b"MZ" + b"0" * 200, "application/octet-stream")}, headers=headers)
    assert res.status_code == 415 and stored(storage_dir) == []


# ---------- employer access ----------

def test_employer_cannot_download_before_acceptance_but_can_after(client, employer, storage_dir):
    job = create_job(client, employer[1])
    _, headers = candidate(client)
    upload(client, headers)
    application = apply(client, job, headers)

    def check_parsed_cv_only():
        assert client.get(cv_url(application, "cv-file"), headers=employer[1]).status_code == 403
        view = client.get(cv_url(application), headers=employer[1])
        assert view.status_code == 200
        body = view.json()
        assert body["cv"]["summary"] and "React" in body["cv"]["skills"]
        assert body["cv"]["education"] and body["cv"]["experience"] and body["cv"]["projects"]
        assert body["file"] is None and body["contact"] is None
        for secret in ("Ayesha", "ayesha.khan@example.com", "1234567", "linkedin", "github", "ayesha_cv"):
            assert secret.lower() not in view.text.lower(), secret
        assert set(body["cv"]) == {"summary", "skills", "otherSkills", "education", "experience", "projects",
                                   "certifications", "experienceYears"}

    check_parsed_cv_only()  # applied
    shortlist(client, application, employer[1])
    check_parsed_cv_only()  # shortlisted, candidate has not answered

    respond(client, application, headers, "accept")
    res = client.get(cv_url(application, "cv-file"), headers=employer[1])
    assert res.status_code == 200
    assert res.content == SAMPLE.read_bytes()
    assert res.headers["content-type"].startswith("text/plain")
    assert "attachment" in res.headers["content-disposition"] and "ayesha_cv.txt" in res.headers["content-disposition"]

    after = client.get(cv_url(application), headers=employer[1]).json()
    assert after["file"]["name"] == "ayesha_cv.txt"
    assert after["contact"]["email"] == "ayesha@example.com" and after["contact"]["name"] == "Ayesha Khan"
    assert "+92 300 1234567" in after["contact"]["phone"]
    assert not {"sessions", "interviewScore", "indicators", "match"} & set(after)


def test_pdf_is_served_inline(client, db, employer, storage_dir):
    job = create_job(client, employer[1])
    _, headers = candidate(client)
    upload(client, headers)
    row = db.query(CvFile).one()
    row.content_type, row.file_name = "application/pdf", "cv.pdf"
    db.commit()
    application = accepted_application(client, employer, headers, job)
    res = client.get(cv_url(application, "cv-file"), headers=employer[1])
    assert res.status_code == 200 and res.headers["content-type"] == "application/pdf"
    assert res.headers["content-disposition"].startswith("inline")


def test_declined_candidate_file_stays_private(client, employer):
    job = create_job(client, employer[1])
    _, headers = candidate(client)
    upload(client, headers)
    application = apply(client, job, headers)
    shortlist(client, application, employer[1])
    respond(client, application, headers, "decline")
    assert client.get(cv_url(application, "cv-file"), headers=employer[1]).status_code == 403
    assert client.get(cv_url(application), headers=employer[1]).json()["contact"] is None


def test_other_employer_and_other_roles_get_403(client, employer, other_employer):
    job = create_job(client, employer[1])
    _, headers = candidate(client)
    upload(client, headers)
    application = accepted_application(client, employer, headers, job)
    for suffix in ("cv", "cv-file"):
        url = cv_url(application, suffix)
        assert client.get(url, headers=other_employer[1]).status_code == 403
        assert client.get(url, headers=headers).status_code == 403
        assert client.get(url).status_code == 401
    assert "Ayesha" not in client.get(cv_url(application), headers=other_employer[1]).text
    assert client.get("/api/applications/app-nope/cv", headers=employer[1]).status_code == 404


def test_applicant_without_consent_is_403(client, employer):
    job = create_job(client, employer[1])
    _, headers = candidate(client)
    upload(client, headers)
    application = client.post(f"/api/jobs/{job['id']}/apply", json={"consent": False}, headers=headers).json()
    assert client.get(cv_url(application), headers=employer[1]).status_code == 403
    assert client.get(cv_url(application, "cv-file"), headers=employer[1]).status_code == 403


def test_missing_stored_file_is_404_after_acceptance(client, db, employer):
    job = create_job(client, employer[1])
    _, headers = candidate(client)
    upload(client, headers)
    application = accepted_application(client, employer, headers, job)
    db.get(Application, application["id"]).cv_file_id = None
    db.commit()
    assert client.get(cv_url(application, "cv-file"), headers=employer[1]).status_code == 404


# ---------- snapshot ----------

def test_snapshot_is_unchanged_when_the_candidate_uploads_a_new_cv(client, employer, storage_dir):
    job = create_job(client, employer[1])
    _, headers = candidate(client)
    upload(client, headers)
    application = apply(client, job, headers)

    def view():
        return client.get(cv_url(application), headers=employer[1]).json()["cv"]

    def match():
        return client.get(f"/api/jobs/{job['id']}/candidates", headers=employer[1]).json()["candidates"][0]["match"]

    before, match_before = view(), match()
    assert "React" in before["skills"] and match_before["percentage"] > 0

    upload(client, headers, "second.txt", SECOND.encode())
    assert len(stored(storage_dir)) == 2  # the first file stays: it is what the employer received
    assert view() == before and match() == match_before
    assert view()["skills"] == before["skills"]

    # the candidate's own CV did change, and a later edit doesn't reach the employer either
    mine = client.get("/api/cv", headers=headers).json()["cv"]
    assert "React" not in mine["skills"] and "Testing" in mine["skills"]
    client.put("/api/cv", json={**mine, "summary": "Edited later"}, headers=headers)
    assert view() == before

    assert shortlist(client, application, employer[1]).status_code == 200
    respond(client, application, headers, "accept")
    res = client.get(cv_url(application, "cv-file"), headers=employer[1])
    assert res.content == SAMPLE.read_bytes() and "ayesha_cv.txt" in res.headers["content-disposition"]

    # a later application gets the new CV
    job2 = create_job(client, employer[1], title="Backend Intern")
    app2 = apply(client, job2, headers)
    assert "React" not in client.get(cv_url(app2), headers=employer[1]).json()["cv"]["skills"]


# ---------- deleting files ----------

def test_withdraw_deletes_the_snapshot_file(client, db, employer, storage_dir):
    job = create_job(client, employer[1])
    _, headers = candidate(client)
    upload(client, headers)
    apply(client, job, headers)
    upload(client, headers, "second.txt", SECOND.encode())
    assert len(stored(storage_dir)) == 2 and db.query(CvFile).count() == 2

    assert client.delete(f"/api/jobs/{job['id']}/apply", headers=headers).status_code == 204
    left = stored(storage_dir)
    assert len(left) == 1  # only the current CV remains
    row = db.query(CvFile).one()
    assert row.file_name == "second.txt" and row.storage_name == left[0]


def test_withdraw_keeps_a_file_that_is_still_in_use(client, employer, storage_dir):
    job1, job2 = create_job(client, employer[1]), create_job(client, employer[1], title="Second job")
    _, headers = candidate(client)
    upload(client, headers)
    apply(client, job1, headers)
    apply(client, job2, headers)
    upload(client, headers, "second.txt", SECOND.encode())
    assert len(stored(storage_dir)) == 2

    client.delete(f"/api/jobs/{job1['id']}/apply", headers=headers)
    assert len(stored(storage_dir)) == 2  # job2 still holds the first file
    client.delete(f"/api/jobs/{job2['id']}/apply", headers=headers)
    assert len(stored(storage_dir)) == 1


def test_deleting_a_candidate_deletes_their_files(client, db, employer, storage_dir):
    job = create_job(client, employer[1])
    _, headers = candidate(client)
    _, other_headers = candidate(client, "Bilal Ahmed", "bilal@example.com")
    upload(client, headers)
    apply(client, job, headers)
    upload(client, headers, "second.txt", SECOND.encode())
    upload(client, other_headers, "bilal.txt")
    assert len(stored(storage_dir)) == 3

    assert client.delete("/api/auth/me", headers=employer[1]).status_code == 403
    assert client.delete("/api/auth/me", headers=headers).status_code == 204
    assert len(stored(storage_dir)) == 1  # only Bilal's remains
    assert db.query(CvFile).one().file_name == "bilal.txt"
    assert client.get("/api/auth/me", headers=headers).status_code == 401
