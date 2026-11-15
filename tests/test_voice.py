"""Speech-to-text and the single evaluation pipeline. A fake speech provider: no network, no key."""

import io
import json
import wave

import pytest

from app.config import settings
from app.models import SessionAnswer
from app.services.ai import speech
from app.services.ai.speech import GroqWhisperProvider, NoSpeechProvider, SpeechProvider, SpeechUnavailable, Transcript
from tests.conftest import employer_payload
from tests.test_interviews import LONG_ANSWER, answer, auth, library, other_auth, rules_only, start  # noqa: F401


def wav_bytes(seconds: float = 0.5, rate: int = 8000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(seconds * rate))
    return buf.getvalue()


class FakeSpeech(SpeechProvider):
    name = "fake"

    def __init__(self, text=LONG_ANSWER, duration=12.0):
        self.text, self.duration, self.calls = text, duration, []

    def transcribe(self, audio, filename, content_type):
        self.calls.append((len(audio), filename, content_type))
        return Transcript(self.text, self.duration, "en", self.name)


@pytest.fixture
def fake(monkeypatch):
    f = FakeSpeech()
    monkeypatch.setattr(speech, "get_speech_provider", lambda: f)
    return f


def url(iv, tail):
    return f"/api/interviews/{iv['id']}/{tail}"


def audio(data=None, name="a.wav", ctype="audio/wav"):
    return {"audio": (name, data if data is not None else wav_bytes(), ctype)}


# ---------- /transcribe ----------

def test_transcribe_returns_the_transcript(client, auth, library, fake):
    iv = start(client, auth)
    res = client.post(url(iv, "transcribe"), headers=auth, files=audio())
    assert res.status_code == 200, res.text
    assert res.json() == {"transcript": LONG_ANSWER, "durationSeconds": 12.0, "language": "en", "provider": "fake"}


def test_transcribe_without_a_provider_is_a_clear_503(client, auth, library, monkeypatch):
    monkeypatch.setattr(settings, "stt_provider", "none")
    iv = start(client, auth)
    res = client.post(url(iv, "transcribe"), headers=auth, files=audio())
    assert res.status_code == 503 and res.json()["detail"] == "Speech-to-text unavailable"


def test_groq_without_a_key_degrades_to_the_503(client, auth, library, monkeypatch):
    monkeypatch.setattr(settings, "stt_provider", "groq")
    monkeypatch.setattr(settings, "groq_api_key", "")
    assert isinstance(speech.get_speech_provider(), NoSpeechProvider)
    iv = start(client, auth)
    assert client.post(url(iv, "transcribe"), headers=auth, files=audio()).status_code == 503


def test_groq_provider_is_selected_with_a_key(monkeypatch):
    monkeypatch.setattr(settings, "stt_provider", "groq")
    monkeypatch.setattr(settings, "groq_api_key", "test-key")
    p = speech.get_speech_provider()
    assert isinstance(p, GroqWhisperProvider) and p._model == settings.whisper_model


def test_provider_failure_is_a_503(client, auth, library, monkeypatch):
    class Broken(SpeechProvider):
        name = "broken"

        def transcribe(self, *a):
            raise SpeechUnavailable("boom")

    monkeypatch.setattr(speech, "get_speech_provider", lambda: Broken())
    iv = start(client, auth)
    assert client.post(url(iv, "transcribe"), headers=auth, files=audio()).status_code == 503


@pytest.mark.parametrize("name,ctype,data,code", [
    ("a.txt", "text/plain", b"hello", 415),
    ("a.wav", "audio/wav", b"not really a wav file at all", 415),  # wrong magic bytes
    ("a.wav", "image/png", wav_bytes(), 415),
    ("a.wav", "audio/wav", b"", 422),
    ("a.wav", "audio/wav", wav_bytes(200, 1000), 422),  # ~200 s
    ("a.wav", "audio/wav", b"RIFF\x00\x00\x00\x00WAVE" + b"\x00" * (10 * 1024 * 1024), 413),
])
def test_transcribe_validates_type_and_size(client, auth, library, fake, name, ctype, data, code):
    iv = start(client, auth)
    res = client.post(url(iv, "transcribe"), headers=auth, files=audio(data, name, ctype))
    assert res.status_code == code, res.text
    assert fake.calls == []


@pytest.mark.parametrize("ext,ctype,head", [
    ("webm", "audio/webm;codecs=opus", b"\x1a\x45\xdf\xa3" + b"\0" * 20), ("ogg", "audio/ogg", b"OggS" + b"\0" * 20),
    ("mp3", "audio/mpeg", b"ID3" + b"\0" * 20), ("m4a", "audio/mp4", b"\0\0\0\x18ftypM4A " + b"\0" * 20),
])
def test_other_audio_formats_are_accepted(client, auth, library, fake, ext, ctype, head):
    iv = start(client, auth)
    res = client.post(url(iv, "transcribe"), headers=auth, files=audio(head, f"a.{ext}", ctype))
    assert res.status_code == 200, res.text


def test_a_long_recording_reported_by_the_provider_is_rejected(client, auth, library, monkeypatch):
    monkeypatch.setattr(speech, "get_speech_provider", lambda: FakeSpeech(duration=400))
    iv = start(client, auth)
    assert client.post(url(iv, "transcribe"), headers=auth, files=audio()).status_code == 422


def test_silence_is_rejected(client, auth, library, monkeypatch):
    monkeypatch.setattr(speech, "get_speech_provider", lambda: FakeSpeech(text="  "))
    iv = start(client, auth)
    assert client.post(url(iv, "transcribe"), headers=auth, files=audio()).status_code == 422


def test_transcribe_is_owner_only_and_candidate_only(client, auth, other_auth, library, fake):
    iv = start(client, auth)
    assert client.post(url(iv, "transcribe"), headers=other_auth, files=audio()).status_code == 404
    assert client.post(url(iv, "transcribe"), files=audio()).status_code == 401
    employer = client.post("/api/auth/signup", json=employer_payload()).json()
    assert client.post(url(iv, "transcribe"), headers={"Authorization": f"Bearer {employer['token']}"},
                       files=audio()).status_code == 403


# ---------- /answers: one pipeline for every mode ----------

def test_voice_answer_is_transcribed_then_evaluated_like_text(client, auth, library, fake):
    iv = start(client, auth)
    q = next(q for q in iv["questions"] if q["type"] == "technical")
    text = answer(client, auth, iv, q, LONG_ANSWER).json()
    iv2 = start(client, auth)
    q2 = next(x for x in iv2["questions"] if x["skill"] == q["skill"] and x["type"] == "technical")
    res = client.post(url(iv2, "answers"), headers=auth, data={"questionId": q2["id"]}, files=audio())
    assert res.status_code == 200, res.text
    voice = res.json()
    assert (voice["score"], voice["criteria"], voice["provider"]) == (text["score"], text["criteria"], text["provider"])
    assert voice["answerSource"] == "voice" and text["answerSource"] == "text"
    assert voice["transcript"] == LONG_ANSWER and "transcript" not in text  # the client shows what was heard
    detail = client.get(f"/api/interviews/{iv2['id']}", headers=auth).json()
    stored = next(a for a in detail["questions"] if a["id"] == q2["id"])
    assert stored["answer"] == LONG_ANSWER and stored["answerSource"] == "voice" and stored["indicators"] is None


def test_video_answer_stores_indicators_and_source(client, auth, library, fake, db):
    iv = start(client, auth, mode="video")
    ind = {"lighting": 80, "framing": 70, "steadiness": 90, "eyeContact": 60, "expressiveness": 50}
    res = client.post(url(iv, "answers"), headers=auth, files=audio(),
                      data={"questionId": iv["questions"][0]["id"], "indicators": json.dumps(ind)})
    assert res.status_code == 200, res.text
    row = db.get(SessionAnswer, res.json()["answerId"])
    assert row.answer_source == "video" and row.indicators == ind and row.answer == LONG_ANSWER


@pytest.mark.parametrize("bad", ['{"eyeContact": 101}', '{"lighting": -1}', '{"framing": "high"}', "not json", "[1]"])
def test_indicator_ranges_are_validated(client, auth, library, fake, bad):
    iv = start(client, auth)
    res = client.post(url(iv, "answers"), headers=auth, files=audio(),
                      data={"questionId": iv["questions"][0]["id"], "indicators": bad})
    assert res.status_code == 422 and fake.calls == []


def test_text_answers_validate_indicators_too(client, auth, library):
    iv = start(client, auth)
    q = iv["questions"][0]
    r = client.post(url(iv, "answers"), headers=auth,
                    json={"questionId": q["id"], "answer": LONG_ANSWER, "indicators": {"eyeContact": 150}})
    assert r.status_code == 422
    ok = client.post(url(iv, "answers"), headers=auth,
                     json={"questionId": q["id"], "answer": LONG_ANSWER, "indicators": {"eyeContact": 80}})
    assert ok.status_code == 200 and ok.json()["answerSource"] == "video"


def test_voice_answer_errors_do_not_consume_the_question(client, auth, library, monkeypatch):
    monkeypatch.setattr(settings, "stt_provider", "none")
    iv = start(client, auth)
    q = iv["questions"][0]
    assert client.post(url(iv, "answers"), headers=auth, data={"questionId": q["id"]}, files=audio()).status_code == 503
    assert answer(client, auth, iv, q, LONG_ANSWER).status_code == 200  # still answerable (browser fallback path)


def test_audio_is_never_stored(db):
    assert [c.name for c in SessionAnswer.__table__.columns if "audio" in c.name or "video" in c.name] == []
