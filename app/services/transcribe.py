"""Validates an uploaded audio answer and turns it into text. The audio lives in memory only
and is discarded afterwards; only the transcript is ever stored."""

import logging

from fastapi import HTTPException, UploadFile, status

from app.services.ai import speech
from app.services.audio_length import audio_seconds
from app.services.ai.speech import SpeechUnavailable, Transcript

log = logging.getLogger("intervo.speech")

MAX_AUDIO_BYTES = 10 * 1024 * 1024
MAX_AUDIO_SECONDS = 190  # "about 3 minutes", with a little slack for encoder padding
ALLOWED_TYPES = {  # extension -> allowed content types (browsers also label audio-only webm/mp4 as video/*)
    "webm": {"audio/webm", "video/webm"}, "ogg": {"audio/ogg", "application/ogg", "video/ogg"},
    "wav": {"audio/wav", "audio/x-wav", "audio/wave", "audio/vnd.wave"}, "mp3": {"audio/mpeg", "audio/mp3"},
    "m4a": {"audio/mp4", "audio/x-m4a", "audio/m4a", "video/mp4"},
}
GENERIC_TYPES = {"application/octet-stream", ""}


def _sniff(head: bytes) -> str | None:
    """The real format, from the file's first bytes."""
    if head[:4] == b"\x1a\x45\xdf\xa3":
        return "webm"
    if head[:4] == b"OggS":
        return "ogg"
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return "wav"
    if head[:3] == b"ID3" or (len(head) > 1 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0):
        return "mp3"
    if head[4:8] == b"ftyp":
        return "m4a"
    return None


def read_audio(upload: UploadFile) -> tuple[bytes, str, str]:
    """Returns (bytes, filename, content type) after checking size and type, or raises 4xx."""
    name = (upload.filename or "audio").rsplit("/", 1)[-1].rsplit("\\", 1)[-1][:100]
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    ctype = (upload.content_type or "").split(";")[0].strip().lower()
    if ext not in ALLOWED_TYPES or (ctype not in GENERIC_TYPES and ctype not in ALLOWED_TYPES[ext]):
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="Upload audio as webm, ogg, wav, mp3 or m4a.")
    data = upload.file.read(MAX_AUDIO_BYTES + 1)
    if len(data) > MAX_AUDIO_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Audio is too large (10 MB maximum).")
    if not data:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="The audio file is empty.")
    if _sniff(data[:16]) != ext:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="The file isn't valid audio for its type.")
    # The length is read from the file itself, before anything is sent to a speech service.
    secs = audio_seconds(ext, data)
    if secs is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="We couldn't read the length of this recording. Record it again.")
    if secs > MAX_AUDIO_SECONDS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Audio is too long (about 3 minutes maximum).")
    return data, name, ctype or f"audio/{ext}"


def transcribe(upload: UploadFile) -> Transcript:
    data, name, ctype = read_audio(upload)
    try:
        result = speech.get_speech_provider().transcribe(data, name, ctype)
    except SpeechUnavailable as e:
        log.warning("speech-to-text unavailable: %s", e)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="Speech-to-text unavailable") from None
    finally:
        del data  # the audio is never stored
    if result.duration_seconds > MAX_AUDIO_SECONDS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Audio is too long (about 3 minutes maximum).")
    if not result.text.strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="We couldn't hear any speech. Please try again.")
    return result
