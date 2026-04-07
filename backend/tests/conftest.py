"""Shared pytest fixtures for backend tests."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent

# Ensure imports like `from app...` resolve from backend/
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Force deterministic test settings regardless of local .env
os.environ["DATABASE_URL"] = f"sqlite:///{(BACKEND_DIR / 'tests' / 'test_suite.db').as_posix()}"
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")
os.environ.setdefault("GOOGLE_CLOUD_API_KEY", "test-key")
os.environ.setdefault("DEFAULT_MODEL", "gemini-3.1-flash-preview")
os.environ.setdefault("UPLOADS_DIR", str((BACKEND_DIR / "tests" / "uploads").resolve()))

from app.config import get_settings

get_settings.cache_clear()

from app.database import Base, SessionLocal, engine
from app.main import app


(BACKEND_DIR / "tests" / "uploads").mkdir(parents=True, exist_ok=True)


@pytest.fixture(autouse=True)
def reset_db():
    """Create a clean schema for every test."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture
def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def sample_subj_image_bytes() -> bytes:
    """Load the shared mixed-content sample image from repo tests assets."""
    path = REPO_ROOT / "tests" / "test_subj.jpeg"
    return path.read_bytes()
