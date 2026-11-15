import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from pydantic import ValidationError

from app.deps import DbSession, require_role
from app.models import User
from app.schemas.interview import AnswerBody, FollowUpBody, StartIn, validate_indicators
from app.services import interview as service
from app.services import transcribe as stt

router = APIRouter(tags=["interviews"])
Candidate = Annotated[User, Depends(require_role("candidate"))]


@router.post("/interviews", status_code=status.HTTP_201_CREATED)
def start(body: StartIn, user: Candidate, db: DbSession) -> dict:
    """Plans the questions (weaknesses, CV gaps, role skills, one behavioural) and opens a session."""
    return service.start(db, user, body)


@router.get("/interviews")
def history(user: Candidate, db: DbSession) -> list[dict]:
    return service.list_interviews(db, user)


@router.get("/interviews/{interview_id}")
def detail(interview_id: str, user: Candidate, db: DbSession) -> dict:
    return service.get_interview(db, user, interview_id)


@router.post("/interviews/{interview_id}/transcribe")
async def transcribe(interview_id: str, audio: UploadFile, user: Candidate, db: DbSession) -> dict:
    """Speech to text (English). Audio is transcribed in memory and discarded."""
    await run_in_threadpool(service.own_open, db, user, interview_id)
    try:
        t = await run_in_threadpool(stt.transcribe, audio)
    finally:
        await audio.close()
    return {"transcript": t.text, "durationSeconds": round(t.duration_seconds, 1), "language": t.language, "provider": t.provider}


@router.post("/interviews/{interview_id}/answers")
async def answer(interview_id: str, request: Request, user: Candidate, db: DbSession) -> dict:
    """A text answer (JSON) or a spoken one (multipart: questionId, audio, optional indicators JSON).
    Spoken answers are transcribed first and then follow the exact same evaluation path as text."""
    if not request.headers.get("content-type", "").startswith("multipart/form-data"):
        try:
            body = AnswerBody.model_validate(await request.json())
        except ValidationError as e:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=json.loads(e.json(include_url=False, include_context=False)))
        except ValueError:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Send a JSON body or a multipart form.")
        return await run_in_threadpool(service.answer, db, user, interview_id, body)

    form = await request.form()
    upload = form.get("audio")
    question_id = form.get("questionId")
    try:
        if not hasattr(upload, "file") or not isinstance(question_id, str) or not question_id.strip():
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Send questionId and an audio file.")
        raw = form.get("indicators")
        try:
            indicators = validate_indicators(json.loads(raw)) if isinstance(raw, str) and raw.strip() else None
            if indicators is not None and not isinstance(indicators, dict):
                raise ValueError("indicators must be an object")
        except ValueError as e:  # includes bad JSON and out-of-range values
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Invalid indicators: {e}")
        await run_in_threadpool(service.own_open, db, user, interview_id)
        t = await run_in_threadpool(stt.transcribe, upload)
        body = AnswerBody(question_id=question_id.strip(), answer=t.text[:service.MAX_ANSWER_CHARS], indicators=indicators)
        result = await run_in_threadpool(service.answer, db, user, interview_id, body, "video" if indicators else "voice")
        return {**result, "transcript": body.answer}  # so the client can show what Whisper heard
    finally:
        await form.close()  # the audio is discarded; only the transcript was stored


@router.post("/interviews/{interview_id}/answers/{answer_id}/follow-up")
def follow_up(interview_id: str, answer_id: str, body: FollowUpBody, user: Candidate, db: DbSession) -> dict:
    return service.follow_up(db, user, interview_id, answer_id, body)


@router.post("/interviews/{interview_id}/finish")
def finish(interview_id: str, user: Candidate, db: DbSession) -> dict:
    return service.finish(db, user, interview_id)


@router.get("/progress")
def progress(user: Candidate, db: DbSession) -> dict:
    return service.progress(db, user)
