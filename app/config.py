from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, read from environment variables and the .env file."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str
    jwt_secret: str
    jwt_expire_minutes: int = 1440
    # Fernet key that encrypts face templates in the database. If empty, a key is derived from JWT_SECRET.
    face_encryption_key: str | None = None
    cors_origins: str = "http://localhost:5173,http://localhost:5174"
    test_database_url: str | None = None

    # Original CV files live in <storage_dir>/cvs (relative paths are from the project root).
    storage_dir: str = "storage"

    # AI provider layer (app/services/ai). Keys are never logged.
    ai_provider: str = "gemini"  # "gemini" or "rules"
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-3.5-flash-lite"
    ai_timeout_seconds: int = 20

    # Speech-to-text (Whisper via Groq). STT_PROVIDER: "groq" or "none".
    stt_provider: str = "none"
    groq_api_key: str | None = None
    whisper_model: str = "whisper-large-v3-turbo"
    stt_timeout_seconds: int = 30

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip().rstrip("/") for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
