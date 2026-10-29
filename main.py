from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.config import get_settings
from app.database import Base, engine
from app.middleware.rate_limit import limiter
from app.middleware.security_headers import SecurityHeadersMiddleware
from app.routers import ai, analytics, auth, budgets, categories, dashboard, demo, diary, expenses, goals, health, income, jobs, notifications, receipts, reports, security, subscriptions, vault, ws
from app.utils.exceptions import AppError
from app.utils.responses import error

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Dev convenience only: creates tables if they don't exist. Real schema
    # changes go through Alembic migrations (migrations/), not this line —
    # this just means `uvicorn app.main:app` works out of the box on a fresh DB.
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    from app.scheduler import shutdown_scheduler, start_scheduler

    start_scheduler()  # no-op unless SCHEDULER_ENABLED=true
    try:
        yield
    finally:
        shutdown_scheduler()


app = FastAPI(
    title=settings.APP_NAME,
    description="ARTHA — Python-based AI-powered personal finance management web application "
    "built using FastAPI and PostgreSQL.",
    version="0.1.0",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(SecurityHeadersMiddleware)


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    return error(message=exc.message, error_code=exc.error_code, status_code=exc.status_code, extra=exc.extra)


app.include_router(auth.router, prefix="/api/v1")
app.include_router(categories.router, prefix="/api/v1")
app.include_router(expenses.router, prefix="/api/v1")
app.include_router(income.router, prefix="/api/v1")
app.include_router(dashboard.router, prefix="/api/v1")
app.include_router(budgets.router, prefix="/api/v1")
app.include_router(analytics.router, prefix="/api/v1")
app.include_router(goals.router, prefix="/api/v1")
app.include_router(health.router, prefix="/api/v1")
app.include_router(ai.router, prefix="/api/v1")
app.include_router(diary.router, prefix="/api/v1")
app.include_router(vault.router, prefix="/api/v1")
app.include_router(receipts.router, prefix="/api/v1")
app.include_router(notifications.router, prefix="/api/v1")
app.include_router(subscriptions.router, prefix="/api/v1")
app.include_router(reports.router, prefix="/api/v1")
app.include_router(ws.router, prefix="/api/v1")
app.include_router(security.router, prefix="/api/v1")
app.include_router(jobs.router, prefix="/api/v1")
app.include_router(demo.router, prefix="/api/v1")


@app.get("/api/v1/health")
async def health():
    return {"success": True, "message": "ARTHA API is running", "data": {"status": "ok"}}


# ---------- Frontend (one-window mode) ----------
# Serves the HTML/CSS/JS frontend from this same server, so the WHOLE app runs
# on one address — http://localhost:8000 — with one command and no second
# terminal, no Live Server, and no CORS involved (same origin).
# Registered LAST on purpose: Starlette matches routes in order, so every
# /api/v1/* route, /docs and /openapi.json win before the catch-all static
# mount below. If the frontend folder is missing (e.g. the Docker image only
# contains backend/), the app simply keeps working as an API-only server.
import logging
from pathlib import Path

from fastapi.staticfiles import StaticFiles

_frontend_dir = Path(__file__).resolve().parents[2] / "frontend"

if _frontend_dir.is_dir():
    app.mount("/", StaticFiles(directory=_frontend_dir, html=True), name="frontend")
else:
    logging.getLogger("artha.main").info(
        "frontend/ folder not found next to backend/ — running as API-only; "
        "serve the frontend separately (e.g. Live Server on port 5500)."
    )
