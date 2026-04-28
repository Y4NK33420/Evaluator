"""Image serving endpoint — added to submissions router."""

from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Submission
from app.services.pdf_pages import render_pdf_page_to_jpeg_bytes

router = APIRouter(prefix="/submissions", tags=["submissions"])


@router.get("/image/{submission_id}")
def serve_image(
    submission_id: str,
    page: int | None = None,
    dpi: int = 160,
    db: Session = Depends(get_db),
):
    """Serve the raw scan image for the canvas overlay."""
    sub = db.get(Submission, submission_id)
    if not sub or not sub.file_path:
        raise HTTPException(404, "Image not found")
    path = Path(sub.file_path)
    if not path.exists():
        raise HTTPException(404, f"File not found on disk: {path}")
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        page_number = page or 1
        if dpi < 72 or dpi > 300:
            raise HTTPException(422, "dpi must be between 72 and 300")
        try:
            jpeg_bytes, page_count = render_pdf_page_to_jpeg_bytes(
                path, page_number=page_number, dpi=dpi
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return Response(
            content=jpeg_bytes,
            media_type="image/jpeg",
            headers={
                "X-Page-Count": str(page_count),
                "X-Page-Number": str(page_number),
            },
        )

    mime_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".png": "image/png", ".pdf": "application/pdf"}
    return FileResponse(str(path), media_type=mime_map.get(suffix, "application/octet-stream"))
