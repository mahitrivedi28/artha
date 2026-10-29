"""
Central configuration. Every secret comes from the environment — nothing is
hardcoded here, and this file is safe to commit (only .env is gitignored).
"""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_NAME: str = "ARTHA"
    ENVIRONMENT: str = "development"  # development | production
    DEBUG: bool = True

    # Postgres in production; overridable to sqlite+aiosqlite for local/test runs.
    DATABASE_URL: str = "postgresql+asyncpg://artha:artha@localhost:5432/artha"

    JWT_SECRET: str = "CHANGE_ME_IN_ENV"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    MAX_LOGIN_ATTEMPTS: int = 5
    LOCKOUT_MINUTES: int = 15
    VAULT_UNLOCK_MINUTES: int = 15  # how long a diary/vault unlock session stays active

    OTP_LENGTH: int = 6
    OTP_EXPIRE_MINUTES: int = 5
    OTP_MAX_ATTEMPTS: int = 5

    CORS_ORIGINS: list[str] = ["http://localhost:5500", "http://127.0.0.1:5500"]

    GEMINI_API_KEY: str = ""  # unused until Phase 5, present so .env.example documents it
    GEMINI_MODEL: str = "gemini-2.0-flash"

    # Phase 8 — real email delivery. Leave SMTP_HOST blank to run in dev mode
    # (OTP/reset codes printed to console instead of emailed) — same
    # graceful-degradation pattern as GEMINI_API_KEY.
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_USE_TLS: bool = True
    SMTP_FROM_EMAIL: str = "no-reply@artha.app"
    SMTP_FROM_NAME: str = "ARTHA"

    # Server-side key for encrypting TOTP secrets at rest (app/services/totp_service.py).
    # Generate a real one with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    # Left blank by default so 2FA works with zero extra config locally — the service
    # derives a dev-only fallback key from JWT_SECRET in that case. A real deployment
    # MUST set this explicitly and separately from JWT_SECRET: they're used for
    # different things (session signing vs. secret-at-rest encryption), and rotating
    # one shouldn't silently invalidate the other.
    APP_ENCRYPTION_KEY: str = ""

    # Background jobs (app/scheduler.py). Disabled by default so the test
    # suite never has cron jobs firing mid-run against the test database —
    # tests call the job functions directly instead. Enable in deployment.
    SCHEDULER_ENABLED: bool = False

    UPLOAD_FOLDER: str = "vault_storage"  # relative to backend/ unless an absolute path is set via env
    MAX_CONTENT_LENGTH: int = 10 * 1024 * 1024  # 10 MB per vault file


@lru_cache
def get_settings() -> Settings:
    return Settings()
