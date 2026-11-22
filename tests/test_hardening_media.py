"""Hardening, CV and voice: the candidate's name stays from the AI, audio length is read before
anything is sent, overlapping jobs count a month once."""

import struct

import pytest
from starlette.formparsers import MultiPartParser

from app.services import audio_length, cv_rules, transcribe
from app.services.ai.prompts import strip_contact
from tests.test_cv import GOOD, FakeProvider, auth as cv_auth, library, upload, use  # noqa: F401
from tests.test_interviews import auth as iv_auth, library as iv_library, start  # noqa: F401
from tests.test_voice import FakeSpeech, audio, wav_bytes


# ---------- 4. the candidate's name never goes to the AI ----------

def test_strip_contact_removes_name_address_and_city():
    cv = ("Sara Malik\nLahore, Pakistan\nAddress: 12 Canal Road\nEmail: sara@x.com\nDate of Birth: 1 Jan 2000\n"
          "Python developer\nSara Malik led the Python team at Acme.\nSkills: Python")
    out = strip_contact(cv, ["Sara Malik"])
    for private in ("Sara", "Malik", "Lahore", "Canal", "sara@x.com", "2000"):
        assert private not in out
    assert "Python developer" in out and "led the Python team at Acme" in out and "Skills: Python" in out


def test_the_cv_prompt_has_no_name(client, cv_auth, library, monkeypatch):
    fake = FakeProvider(GOOD)
    use(monkeypatch, fake)
    cv = ("Zainab Riaz\nFrontend developer\nLahore, Pakistan\nAddress: House 4, Model Town\n"
          "Skills: React, Git\nZainab Riaz built a shop in React.")
    assert upload(client, cv_auth, data=cv.encode()).status_code == 200
    sent = fake.prompts[0]
    for private in ("Zainab", "Riaz", "Ayesha", "Khan", "Model Town", "Lahore"):
        assert private not in sent
    assert "React" in sent


# ---------- 5. audio length is read before anything is sent ----------

def _el(eid: bytes, payload: bytes) -> bytes:
    return eid + bytes([0x80 | len(payload)]) + payload  # payloads here are under 127 bytes


def ebml_webm(seconds: float, with_duration: bool = False) -> bytes:
    def block(ms: int) -> bytes:
        return _el(b"\xa3", b"\x81" + struct.pack(">h", ms) + b"\x80" + b"\0" * 8)

    blocks = b"".join(block(ms) for ms in range(0, 1000, 250))
    last_cluster_ms = int(seconds * 1000) - 750
    clusters = b"".join(
        _el(b"\x1f\x43\xb6\x75", _el(b"\xe7", tc.to_bytes(4, "big")) + blocks) for tc in (0, last_cluster_ms)
    )
    info = _el(b"\x15\x49\xa9\x66", _el(b"\x2a\xd7\xb1", (1_000_000).to_bytes(3, "big"))
               + (_el(b"\x44\x89", struct.pack(">d", seconds * 1000)) if with_duration else b""))
    header = _el(b"\x1a\x45\xdf\xa3", _el(b"\x42\x82", b"webm"))
    return header + b"\x18\x53\x80\x67" + b"\x01\xff\xff\xff\xff\xff\xff\xff" + info + clusters  # unknown-size segment


def mp3_bytes(frames: int) -> bytes:
    return (b"\xff\xfb\x90\x00" + b"\0" * 413) * frames  # MPEG-1 layer 3, 128 kbps, 44.1 kHz: 26 ms each


def test_audio_length_readers():
    assert audio_length.audio_seconds("wav", wav_bytes(2.0)) == pytest.approx(2.0, abs=0.01)
    assert audio_length.audio_seconds("webm", ebml_webm(12)) == pytest.approx(12, abs=0.1)  # no Duration element
    assert audio_length.audio_seconds("webm", ebml_webm(30, with_duration=True)) == pytest.approx(30, abs=0.1)
    assert audio_length.audio_seconds("mp3", mp3_bytes(200)) == pytest.approx(200 * 1152 / 44100, abs=0.2)
    assert audio_length.audio_seconds("webm", b"\x1a\x45\xdf\xa3" + b"\0" * 20) is None
    assert audio_length.audio_seconds("ogg", b"OggS" + b"\0" * 20) is None


@pytest.mark.parametrize("name,ctype,data", [
    ("a.webm", "audio/webm;codecs=opus", ebml_webm(400)),
    ("a.mp3", "audio/mpeg", mp3_bytes(8000)),  # ~209 s
    ("a.wav", "audio/wav", wav_bytes(200, 1000)),
])
def test_a_long_recording_is_refused_before_it_is_sent(client, iv_auth, iv_library, monkeypatch, name, ctype, data):
    fake = FakeSpeech()
    monkeypatch.setattr(transcribe.speech, "get_speech_provider", lambda: fake)
    iv = start(client, iv_auth)
    res = client.post(f"/api/interviews/{iv['id']}/transcribe", headers=iv_auth, files=audio(data, name, ctype))
    assert res.status_code == 422 and "too long" in res.json()["detail"]
    assert fake.calls == []  # nothing reached the speech service


def test_a_recording_with_an_unreadable_length_is_refused(client, iv_auth, iv_library, monkeypatch):
    fake = FakeSpeech()
    monkeypatch.setattr(transcribe.speech, "get_speech_provider", lambda: fake)
    iv = start(client, iv_auth)
    res = client.post(f"/api/interviews/{iv['id']}/transcribe", headers=iv_auth,
                      files=audio(b"OggS" + b"\0" * 20, "a.ogg", "audio/ogg"))
    assert res.status_code == 422 and fake.calls == []


def test_a_recording_within_the_limit_is_sent(client, iv_auth, iv_library, monkeypatch):
    fake = FakeSpeech()
    monkeypatch.setattr(transcribe.speech, "get_speech_provider", lambda: fake)
    iv = start(client, iv_auth)
    res = client.post(f"/api/interviews/{iv['id']}/transcribe", headers=iv_auth,
                      files=audio(ebml_webm(20), "a.webm", "audio/webm"))
    assert res.status_code == 200 and len(fake.calls) == 1


def test_uploads_stay_in_memory():
    assert MultiPartParser.spool_max_size >= transcribe.MAX_AUDIO_BYTES


# ---------- 9. experience: overlapping jobs count a month once ----------

def test_overlapping_jobs_are_merged():
    jobs = [{"dates": "Jan 2020 - Dec 2020", "months": 11}, {"dates": "Jun 2020 - Jun 2021", "months": 12}]
    assert cv_rules.merged_months(jobs) == 17  # Jan 2020 .. Jun 2021, not 11 + 12
    assert cv_rules.years_from_months(jobs) == 1.5  # adding them up would give 2.0


def test_merge_handles_nested_touching_and_loose_jobs():
    nested = [{"dates": "Jan 2020 - Dec 2021"}, {"dates": "Mar 2020 - Jun 2020"}]
    assert cv_rules.merged_months(nested) == 23
    touching = [{"dates": "Jan 2020 - Jun 2020"}, {"dates": "Jun 2020 - Dec 2020"}]
    assert cv_rules.merged_months(touching) == 11
    apart = [{"dates": "Jan 2020 - Jun 2020"}, {"dates": "Jan 2022 - Jun 2022"}]
    assert cv_rules.merged_months(apart) == 10
    assert cv_rules.merged_months([{"dates": "2 years", "months": 6}, {"dates": "Jan 2020 - Jun 2020"}]) == 11


def test_experience_years_merge_overlaps_end_to_end(client, cv_auth, library, monkeypatch):
    two = {**GOOD, "experience": [
        {"title": "Developer", "company": "Acme", "dates": "Jan 2020 - Dec 2020", "details": "", "months": 11},
        {"title": "Freelancer", "company": "Self", "dates": "Jun 2020 - Jun 2021", "details": "", "months": 12},
    ]}
    use(monkeypatch, FakeProvider(two))
    cv = upload(client, cv_auth).json()["cv"]
    assert [e["months"] for e in cv["experience"]] == [11, 12]  # each job keeps its own length
    assert cv["experienceYears"] == 1.5  # but the total counts overlapping months once
