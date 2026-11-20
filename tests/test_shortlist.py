"""Shortlist flow: notifications, candidate accept/decline and contact sharing."""

from tests.conftest import candidate_payload
from tests.test_employer import (  # noqa: F401  (fixtures: catalog is autouse)
    ayesha, catalog, create_job, employer, other_employer, signup,
)

PHONE = "0300-1234567"


def apply(client, job, headers):
    res = client.post(f"/api/jobs/{job['id']}/apply", json={"consent": True}, headers=headers)
    assert res.status_code == 201, res.text
    return res.json()


def shortlist(client, application, headers, message=None):
    body = {"status": "shortlisted", **({"message": message} if message else {})}
    return client.patch(f"/api/applications/{application['id']}/status", json=body, headers=headers)


def respond(client, application, headers, decision, note=None):
    return client.post(f"/api/applications/{application['id']}/respond",
                       json={"decision": decision, **({"note": note} if note else {})}, headers=headers)


def candidate_entry(client, job, headers):
    return client.get(f"/api/jobs/{job['id']}/candidates", headers=headers).json()["candidates"][0]


def test_shortlist_notifies_the_candidate(client, employer, ayesha):
    job = create_job(client, employer[1])
    application = apply(client, job, ayesha[1])
    assert client.get("/api/notifications/unread-count", headers=ayesha[1]).json() == {"count": 0}

    res = shortlist(client, application, employer[1], "We liked your portfolio.")
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "shortlisted" and res.json()["employerMessage"] == "We liked your portfolio."

    assert client.get("/api/notifications/unread-count", headers=ayesha[1]).json() == {"count": 1}
    notes = client.get("/api/notifications", headers=ayesha[1]).json()
    assert len(notes) == 1
    assert notes[0]["type"] == "shortlisted" and notes[0]["read"] is False and notes[0]["readAt"] is None
    assert job["title"] in notes[0]["title"] and "We liked your portfolio." in notes[0]["body"]
    assert notes[0]["link"] == "/applications"
    assert client.get("/api/notifications", headers=employer[1]).json() == []  # not the employer's

    mine = client.get("/api/applications/mine", headers=ayesha[1]).json()
    assert len(mine) == 1
    assert mine[0]["status"] == "shortlisted" and mine[0]["employerMessage"] == "We liked your portfolio."
    assert mine[0]["jobTitle"] == job["title"] and mine[0]["company"] == "Northstar Digital"
    assert [h["status"] for h in mine[0]["history"]] == ["applied", "shortlisted"]
    assert mine[0]["history"][1]["employerMessage"] == "We liked your portfolio."


def test_not_progressing_notifies_the_candidate(client, employer, ayesha):
    job = create_job(client, employer[1])
    application = apply(client, job, ayesha[1])
    res = client.patch(f"/api/applications/{application['id']}/status",
                       json={"status": "not_progressing"}, headers=employer[1])
    assert res.status_code == 200 and res.json()["status"] == "not_progressing"
    note = client.get("/api/notifications", headers=ayesha[1]).json()[0]
    assert note["type"] == "not_progressing"
    # a rejected candidate can't respond
    assert respond(client, application, ayesha[1], "accept").status_code == 409


def test_message_limit_and_transitions(client, employer, ayesha):
    job = create_job(client, employer[1])
    application = apply(client, job, ayesha[1])
    assert shortlist(client, application, employer[1], "x" * 501).status_code == 422
    assert shortlist(client, application, employer[1], "x" * 500).status_code == 200
    assert shortlist(client, application, employer[1]).status_code == 409  # already shortlisted
    assert respond(client, application, ayesha[1], "accept").status_code == 200
    # once the candidate has answered the employer can no longer change anything
    assert shortlist(client, application, employer[1]).status_code == 409
    res = client.patch(f"/api/applications/{application['id']}/status",
                       json={"status": "not_progressing"}, headers=employer[1])
    assert res.status_code == 409


def test_no_contact_before_accept(client, employer, ayesha):
    job = create_job(client, employer[1])
    application = apply(client, job, ayesha[1])
    shortlist(client, application, employer[1])

    employer_view = client.get(f"/api/jobs/{job['id']}/candidates", headers=employer[1])
    assert "contact" not in employer_view.json()["candidates"][0]
    assert "ayesha@example.com" not in employer_view.text and PHONE not in employer_view.text

    candidate_view = client.get("/api/applications/mine", headers=ayesha[1])
    assert candidate_view.json()[0]["employer"] is None
    assert "hr@example.com" not in candidate_view.text
    # nor in the notifications either side has received
    assert "hr@example.com" not in client.get("/api/notifications", headers=ayesha[1]).text
    assert "ayesha@example.com" not in client.get("/api/notifications", headers=employer[1]).text
    jobs_text = client.get("/api/jobs", headers=employer[1]).text
    assert "ayesha@example.com" not in jobs_text and PHONE not in jobs_text


def test_accept_reveals_contacts_to_both(client, employer, ayesha):
    job = create_job(client, employer[1])
    application = apply(client, job, ayesha[1])
    shortlist(client, application, employer[1])

    res = respond(client, application, ayesha[1], "accept", "Happy to talk!")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "accepted" and body["candidateNote"] == "Happy to talk!"
    assert body["employer"] == {"name": "Hira Malik", "company": "Northstar Digital", "email": "hr@example.com"}
    assert client.get("/api/applications/mine", headers=ayesha[1]).json()[0]["employer"]["email"] == "hr@example.com"

    entry = candidate_entry(client, job, employer[1])
    assert entry["application"]["status"] == "accepted"
    assert entry["contact"] == {"name": "Ayesha Khan", "email": "ayesha@example.com", "phone": PHONE}

    note = client.get("/api/notifications", headers=employer[1]).json()[0]
    assert note["type"] == "accepted" and "Happy to talk!" in note["body"]
    assert note["link"] == f"/candidates?job={job['id']}"


def test_contact_phone_is_null_without_a_cv(client, db, employer):
    from app.models import CandidateProfile
    user, headers = signup(client, candidate_payload(email="noncv@example.com", name="Noor Cv"))
    db.get(CandidateProfile, user["id"]).skills = ["React"]
    db.commit()
    job = create_job(client, employer[1])
    application = apply(client, job, headers)
    shortlist(client, application, employer[1])
    respond(client, application, headers, "accept")
    assert candidate_entry(client, job, employer[1])["contact"] == {
        "name": "Noor Cv", "email": "noncv@example.com", "phone": None}


def test_decline_reveals_nothing(client, employer, ayesha):
    job = create_job(client, employer[1])
    application = apply(client, job, ayesha[1])
    shortlist(client, application, employer[1])

    res = respond(client, application, ayesha[1], "decline", "Took another offer.")
    assert res.status_code == 200 and res.json()["status"] == "declined_by_candidate"
    assert res.json()["employer"] is None and "hr@example.com" not in res.text

    employer_view = client.get(f"/api/jobs/{job['id']}/candidates", headers=employer[1])
    entry = employer_view.json()["candidates"][0]
    assert entry["application"]["status"] == "declined_by_candidate"
    assert entry["application"]["candidateNote"] == "Took another offer."
    assert "contact" not in entry
    assert "ayesha@example.com" not in employer_view.text and PHONE not in employer_view.text

    note = client.get("/api/notifications", headers=employer[1]).json()[0]
    assert note["type"] == "declined" and "Took another offer." in note["body"]
    assert "ayesha@example.com" not in note["body"]


def test_only_the_job_owner_can_change_status(client, employer, other_employer, ayesha):
    job = create_job(client, employer[1])
    application = apply(client, job, ayesha[1])
    rival = other_employer[1]
    assert shortlist(client, application, rival).status_code == 403
    assert client.patch(f"/api/applications/{application['id']}/status",
                        json={"status": "not_progressing"}, headers=rival).status_code == 403
    assert shortlist(client, application, ayesha[1]).status_code == 403  # candidates can't either
    assert client.patch("/api/applications/app-missing/status", json={"status": "shortlisted"},
                        headers=employer[1]).status_code == 404
    assert client.get("/api/notifications", headers=ayesha[1]).json() == []  # nothing happened
    assert client.get("/api/applications/mine", headers=ayesha[1]).json()[0]["status"] == "applied"


def test_candidate_cannot_respond_twice_or_early(client, employer, ayesha):
    job = create_job(client, employer[1])
    application = apply(client, job, ayesha[1])
    assert respond(client, application, ayesha[1], "accept").status_code == 409  # not shortlisted yet

    shortlist(client, application, employer[1])
    assert respond(client, application, ayesha[1], "maybe").status_code == 422
    assert respond(client, application, ayesha[1], "accept", "n" * 501).status_code == 422
    assert respond(client, application, ayesha[1], "decline").status_code == 200
    assert respond(client, application, ayesha[1], "accept").status_code == 409  # can't change their mind
    assert respond(client, application, ayesha[1], "decline").status_code == 409
    assert client.get("/api/applications/mine", headers=ayesha[1]).json()[0]["status"] == "declined_by_candidate"
    assert len(client.get("/api/notifications", headers=employer[1]).json()) == 1  # only the first answer


def test_candidate_cannot_respond_to_someone_elses_application(client, employer, ayesha):
    job = create_job(client, employer[1])
    application = apply(client, job, ayesha[1])
    shortlist(client, application, employer[1])
    _, bilal = signup(client, candidate_payload(email="bilal@example.com", name="Bilal Ahmed"))

    assert respond(client, application, bilal, "accept").status_code == 403
    assert client.get("/api/applications/mine", headers=bilal).json() == []
    assert respond(client, application, employer[1], "accept").status_code == 403  # employers can't respond
    assert respond(client, {"id": "app-missing"}, ayesha[1], "accept").status_code == 404
    assert client.get("/api/applications/mine", headers=ayesha[1]).json()[0]["status"] == "shortlisted"
    assert client.get("/api/applications/mine", headers=employer[1]).status_code == 403
    assert client.get("/api/applications/mine").status_code == 401


def test_notifications_read_and_read_all(client, employer, ayesha):
    for title in ("Dev A", "Dev B"):
        job = create_job(client, employer[1], title=title)
        shortlist(client, apply(client, job, ayesha[1]), employer[1])
    headers = ayesha[1]
    assert client.get("/api/notifications/unread-count", headers=headers).json() == {"count": 2}

    first = client.get("/api/notifications", headers=headers).json()[0]
    res = client.post(f"/api/notifications/{first['id']}/read", headers=headers)
    assert res.status_code == 200 and res.json()["read"] is True and res.json()["readAt"] is not None
    assert client.get("/api/notifications/unread-count", headers=headers).json() == {"count": 1}

    # someone else's notification is a 404, and stays unread
    assert client.post(f"/api/notifications/{first['id']}/read", headers=employer[1]).status_code == 404
    assert client.post("/api/notifications/ntf-missing/read", headers=headers).status_code == 404
    assert client.post("/api/notifications/read-all", headers=employer[1]).status_code == 200

    assert client.post("/api/notifications/read-all", headers=headers).json() == {"count": 0}
    assert client.get("/api/notifications/unread-count", headers=headers).json() == {"count": 0}
    assert all(n["read"] for n in client.get("/api/notifications", headers=headers).json())
    assert client.get("/api/notifications").status_code == 401


def test_employer_still_never_sees_interview_scores(client, employer, ayesha):
    job = create_job(client, employer[1])
    application = apply(client, job, ayesha[1])
    shortlist(client, application, employer[1])
    respond(client, application, ayesha[1], "accept")
    text = client.get(f"/api/jobs/{job['id']}/candidates", headers=employer[1]).text.lower()
    for word in ("session", "interview", "avgscore", "indicators", "followup", "trend"):
        assert word not in text, word


def test_my_applications_route_answers_get_for_a_candidate(client, ayesha):
    """GET /api/applications/mine must be a real GET route (not shadowed by /applications/{id}...)."""
    res = client.get("/api/applications/mine", headers=ayesha[1])
    assert res.status_code == 200, res.text
    assert res.json() == []
    # Notification routes the bell uses: right verbs, not swallowed by /notifications/{id}/read.
    assert client.get("/api/notifications/unread-count", headers=ayesha[1]).status_code == 200
    assert client.post("/api/notifications/read-all", headers=ayesha[1]).status_code == 200
