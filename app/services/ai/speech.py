"""Speech-to-text providers. Audio is only ever held in memory and sent for transcription; it is
never written to the database or to disk by this app."""

import io
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.config import settings

log = logging.getLogger("intervo.speech")


class SpeechUnavailable(Exception):
    """No provider is configured, or it failed. The frontend falls back to browser speech recognition."""


@dataclass
class Transcript:
    text: str
    duration_seconds: float
    language: str
    provider: str


class SpeechProvider(ABC):
    name: str

    @abstractmethod
    def transcribe(self, audio: bytes, filename: str, content_type: str) -> Transcript:
        """English-only transcription. Raises SpeechUnavailable on any provider failure."""


class NoSpeechProvider(SpeechProvider):
    name = "none"

    def transcribe(self, audio: bytes, filename: str, content_type: str) -> Transcript:
        raise SpeechUnavailable("STT_PROVIDER is not enabled")


class GroqWhisperProvider(SpeechProvider):
    name = "groq"

    def __init__(self, api_key: str, model: str, timeout_seconds: int = 30):
        if not api_key:
            raise SpeechUnavailable("GROQ_API_KEY is not set")
        from groq import Groq

        self._model = model
        self._client = Groq(api_key=api_key, timeout=timeout_seconds, max_retries=1)

    def transcribe(self, audio: bytes, filename: str, content_type: str) -> Transcript:
        try:
            res = self._client.audio.transcriptions.create(
                file=(filename, io.BytesIO(audio), content_type), model=self._model,
                language="en", response_format="verbose_json", temperature=0.0,
            )
        except Exception as e:  # never log the request: log the error type only
            log.warning("Groq transcription failed (%s)", type(e).__name__)
            raise SpeechUnavailable(f"Groq call failed ({type(e).__name__})") from None
        return Transcript(
            text=(getattr(res, "text", "") or "").strip(),
            duration_seconds=float(getattr(res, "duration", 0) or 0),
            language="en",  # English only; Groq reports the name ("English"), we return the code
            provider=self.name,
        )


def get_speech_provider() -> SpeechProvider:
    """Chosen by STT_PROVIDER (groq | none). Anything that can't be set up becomes NoSpeechProvider."""
    if settings.stt_provider.strip().lower() == "groq":
        try:
            return GroqWhisperProvider(settings.groq_api_key or "", settings.whisper_model, settings.stt_timeout_seconds)
        except SpeechUnavailable as e:
            log.warning("Speech-to-text unavailable (%s)", e)
        except Exception as e:
            log.warning("Groq could not be set up (%s)", type(e).__name__)
    return NoSpeechProvider()
