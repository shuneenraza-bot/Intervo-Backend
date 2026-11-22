from fastapi import APIRouter, FastAPI
from starlette.formparsers import MultiPartParser
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import admin, applications, auth, candidate, cv, health, interviews, jobs, notifications

# Uploads (CV 5 MB, audio 10 MB) are held in memory. By default Starlette moves any upload over
# 1 MB to a temporary file on disk, which would put recordings on disk for the length of a request.
MultiPartParser.spool_max_size = 12 * 1024 * 1024

app = FastAPI(title="Intervo API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Retry-After", "Content-Disposition"],  # Retry-After: the sign-in countdown on 429; Content-Disposition: the CV download name
)

api = APIRouter(prefix="/api")
api.include_router(health.router)
api.include_router(auth.router)
api.include_router(jobs.router)
api.include_router(applications.router)
api.include_router(notifications.router)
api.include_router(candidate.router)
api.include_router(cv.router)
api.include_router(interviews.router)
api.include_router(admin.router)
app.include_router(api)
