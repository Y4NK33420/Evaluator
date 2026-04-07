"""Image serving endpoint — added to submissions router."""

from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Submission

router = APIRouter(prefix="/submissions", tags=["submissions"])


@router.get("/image/{submission_id}")
def serve_image(submission_id: str, db: Session = Depends(get_db)):
    """Serve the raw scan image for the canvas overlay."""
    sub = db.get(Submission, submission_id)
    if not sub or not sub.file_path:
        raise HTTPException(404, "Image not found")
    path = Path(sub.file_path)
    if not path.exists():
        raise HTTPException(404, f"File not found on disk: {path}")
    suffix   = path.suffix.lower()
    mime_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".png": "image/png", ".pdf": "application/pdf"}
    return FileResponse(str(path), media_type=mime_map.get(suffix, "application/octet-stream"))
