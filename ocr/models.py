"""
OCR data models.
All coordinates are normalised to [0, 1000] relative to image width/height.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class BlockLabel(str, Enum):
    text    = "text"
    title   = "title"
    table   = "table"
    formula = "formula"
    figure  = "figure"
    other   = "other"


class OCRBlock(BaseModel):
    """Single detected region with its OCR text and quality metadata."""
    index:      int
    label:      str                        # PP-DocLayout class name
    content:    str
    bbox_2d:    list[int]                  # [x1, y1, x2, y2] in 0-1000 space
    confidence: float = Field(ge=0.0, le=1.0)
    flagged:    bool   = False             # True when confidence < threshold
    error:      Optional[str] = None       # set when OCR failed for this block


class OCRResult(BaseModel):
    """Result for a single image."""
    id:             str
    blocks:         list[OCRBlock] = []
    flagged_count:  int = 0
    block_count:    int = 0
    processing_ms:  float = 0.0
    error:          Optional[str] = None   # set when entire image failed


class OCRBatchResult(BaseModel):
    """Result for a batch of images."""
    results:    list[OCRResult]
    total_ms:   float


# ── Request models (used by the FastAPI service) ────────────────────────────


class ImageInput(BaseModel):
    """One image in a batch request. Provide either `data` (base64) or `url`."""
    id:   str
    data: Optional[str] = None   # base64-encoded bytes
    url:  Optional[str] = None   # file:// or http:// URL
    mime: str = "image/jpeg"


class OCROptions(BaseModel):
    confidence_threshold:   float = 0.85
    layout_threshold:       float = 0.40
    max_tokens_per_region:  int   = 400
    ocr_retries:            int   = 3


class OCRBatchRequest(BaseModel):
    images:  list[ImageInput]
    options: OCROptions = Field(default_factory=OCROptions)


class OCRSingleRequest(BaseModel):
    image:   ImageInput
    options: OCROptions = Field(default_factory=OCROptions)
