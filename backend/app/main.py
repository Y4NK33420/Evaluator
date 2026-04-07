"""FastAPI application entry point."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import Base, engine
from app.api.v1 import assignments, submissions, rubrics, grades, images, code_eval

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create all tables on startup (Alembic handles migrations in production)
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title       = settings.app_name,
    description = "Automated Marksheet Grading System API",
    version     = "1.0.0",
    docs_url    = "/docs",
    lifespan    = lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins     = ["*"],
    allow_credentials = True,
    allow_methods     = ["*"],
    allow_headers     = ["*"],
)

# ── Routes ────────────────────────────────────────────────────────────────────
prefix = "/api/v1"
app.include_router(assignments.router, prefix=prefix)
app.include_router(submissions.router, prefix=prefix)
app.include_router(rubrics.router,     prefix=prefix)
app.include_router(grades.router,      prefix=prefix)
app.include_router(images.router,      prefix=prefix)
app.include_router(code_eval.router,   prefix=prefix)


@app.get("/health", tags=["ops"])
def health():
    return {"status": "ok", "service": settings.app_name}
