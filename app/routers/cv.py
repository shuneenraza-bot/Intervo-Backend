import os
from typing import Annotated

from fastapi import APIRouter, Depends, File, UploadFile

from app.deps import DbSession, require_role
from app.models import User
from app.schemas.cv import CVResponse, JDParseIn, JDParseOut, MatchIn, MatchOut, ParsedCV
from app.services import cv as cv_service
from app.services.cv_text import MAX_FILE_BYTES, extract_text

router = APIRouter(tags=["cv"])

Candidate = Annotated[User, Depends(require_role("candidate"))]


# "/cv/analyze" is the path the frontend's API.md uses; it is the same endpoint.
@router.post("/cv", response_model=CVResponse)
@router.post("/cv/analyze", response_model=CVResponse, include_in_schema=False)
def upload_cv(user: Candidate, db: DbSession, file: Annotated[UploadFile, File(description="PDF, DOCX or TXT, max 5 MB")]):
    """Reads a CV (PDF/DOCX/TXT, max 5 MB), parses it and saves the result on the candidate's profile.
    `provider` says whether Gemini or the rule-based parser produced it."""
    data = file.file.read(MAX_FILE_BYTES + 1)  # never read more than the limit allows
    file_name = os.path.basename((file.filename or "cv").replace("\\", "/"))[:255] or "cv"
    text = extract_text(file_name, data)
    return cv_service.analyze_and_save(db, user, text, file_name)


@router.get("/cv", response_model=CVResponse)
def get_cv(user: Candidate, db: DbSession):
    return cv_service.get_saved(db, user)


@router.put("/cv", response_model=CVResponse)
def save_cv(body: ParsedCV, user: Candidate, db: DbSession):
    """Saves the user's edits to the parsed CV."""
    return cv_service.save_edits(db, user, body)


@router.post("/cv/match", response_model=MatchOut)
def match_cv(body: MatchIn, user: Candidate, db: DbSession):
    """Compares the saved CV with a role (roleId) or a parsed job description (jd). Deterministic."""
    return cv_service.match(db, user, body)


@router.post("/jd/parse", response_model=JDParseOut)
def parse_jd(body: JDParseIn, user: Candidate, db: DbSession):
    """Job description text -> required skills with weights (3 = must, 2 = normal, 1 = nice to have)."""
    return cv_service.parse_jd(db, body)
