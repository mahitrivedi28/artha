import asyncio

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Force an in-memory sqlite DB for the whole test session BEFORE importing the
# app, so app.database picks it up via settings. This is exactly why the GUID
# type decorator exists — same models, no Postgres required for CI/local tests.
import os
import tempfile

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["JWT_SECRET"] = "test-secret-not-for-production"
os.environ["UPLOAD_FOLDER"] = tempfile.mkdtemp(prefix="artha_test_vault_")

from app.database import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.middleware.rate_limit import limiter  # noqa: E402

test_engine = create_async_engine(os.environ["DATABASE_URL"], future=True)
TestSessionLocal = async_sessionmaker(bind=test_engine, expire_on_commit=False, class_=AsyncSession)


@pytest_asyncio.fixture(autouse=True)
async def _setup_db():
    limiter.reset()
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def _override_get_db():
    async with TestSessionLocal() as session:
        yield session


app.dependency_overrides[get_db] = _override_get_db


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def db_session():
    """A raw session for tests that call service/job functions directly
    instead of going through HTTP — background jobs in particular run
    outside the request lifecycle, so there's no endpoint to drive them
    through. Uses the same session factory as the app's get_db override so
    both see the same in-memory database."""
    async with TestSessionLocal() as session:
        yield session
