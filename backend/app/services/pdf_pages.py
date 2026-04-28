"""Utilities for rendering PDF pages to JPEG bytes."""

from __future__ import annotations

from pathlib import Path


def _load_fitz():
    try:
        import fitz  # type: ignore
    except Exception as exc:  # pragma: no cover - dependency/runtime error
        raise RuntimeError(
            "PyMuPDF is required for PDF page rendering. "
            "Install dependency 'PyMuPDF'."
        ) from exc
    return fitz


def render_pdf_to_jpeg_bytes(
    pdf_path: Path,
    *,
    dpi: int = 180,
    max_pages: int | None = None,
) -> list[bytes]:
    """Render all PDF pages as JPEG bytes."""
    fitz = _load_fitz()
    if dpi <= 0:
        raise ValueError("dpi must be positive")

    pages: list[bytes] = []
    zoom = dpi / 72.0
    with fitz.open(pdf_path) as doc:
        if doc.page_count == 0:
            raise ValueError("PDF has no pages")
        for page_index in range(doc.page_count):
            if max_pages is not None and page_index >= max_pages:
                break
            page = doc.load_page(page_index)
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
            pages.append(pix.tobytes("jpeg"))
    return pages


def render_pdf_page_to_jpeg_bytes(
    pdf_path: Path,
    *,
    page_number: int,
    dpi: int = 160,
) -> tuple[bytes, int]:
    """Render one 1-based PDF page to JPEG and return (bytes, total_page_count)."""
    fitz = _load_fitz()
    if page_number < 1:
        raise ValueError("page_number must be >= 1")
    if dpi <= 0:
        raise ValueError("dpi must be positive")

    zoom = dpi / 72.0
    with fitz.open(pdf_path) as doc:
        total_pages = doc.page_count
        if total_pages == 0:
            raise ValueError("PDF has no pages")
        if page_number > total_pages:
            raise ValueError(f"page_number {page_number} exceeds page count {total_pages}")
        page = doc.load_page(page_number - 1)
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        return pix.tobytes("jpeg"), total_pages
