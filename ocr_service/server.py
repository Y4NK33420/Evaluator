"""
OCR FastAPI microservice.

Endpoints
---------
GET  /v1/health             liveness probe
GET  /v1/status             model status + GPU info
POST /v1/ocr/process        single image → OCRResult
POST /v1/ocr/batch          up to 32 images → OCRBatchResult

The service owns the LayoutDetector singleton and a single OCRPipeline.
Both are initialised once at startup via lifespan().
"""

from __future__ import annotations

import base64
import logging
import os
import sys
from contextlib import asynccontextmanager
from typing import Optional

import torch
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

# Add repo root to path so `ocr` package is found
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from ocr import OCRPipeline, OCROptions
from ocr.models import (
    ImageInput,
    OCRBatchRequest,
    OCRBatchResult,
    OCRResult,
    OCRSingleRequest,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(name)s | %(message)s")
log = logging.getLogger("ocr_service")

# ── Config from env ───────────────────────────────────────────────────────────

VLLM_URL        = os.getenv("VLLM_URL",        "http://vllm-server:8080/v1")
VLLM_MODEL      = os.getenv("VLLM_MODEL",      "glm-ocr")
LAYOUT_MODEL    = os.getenv("LAYOUT_MODEL",    "PaddlePaddle/PP-DocLayoutV3_safetensors")
MAX_BATCH_SIZE  = int(os.getenv("MAX_BATCH_SIZE", "32"))

_pipeline: Optional[OCRPipeline] = None


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _pipeline
    log.info("Loading OCR pipeline (vllm=%s, layout=%s)...", VLLM_URL, LAYOUT_MODEL)
    _pipeline = OCRPipeline(
        vllm_url      = VLLM_URL,
        model_name    = VLLM_MODEL,
        layout_model  = LAYOUT_MODEL,
        preload_layout= True,
    )
    log.info("OCR service ready. Health: %s", _pipeline.health())
    yield
    log.info("OCR service shutting down.")


app = FastAPI(
    title       = "OCR Service",
    description = "GLM-OCR + PP-DocLayoutV3 OCR microservice",
    version     = "1.0.0",
    lifespan    = lifespan,
)


# ── Error handler ─────────────────────────────────────────────────────────────

@app.exception_handler(Exception)
async def _generic_error(request: Request, exc: Exception):
    log.exception("Unhandled error: %s", exc)
    return JSONResponse(status_code=500, content={"detail": str(exc)})


# ── Health & Status ───────────────────────────────────────────────────────────

@app.get("/v1/health", tags=["ops"])
async def health():
    """Liveness probe — always returns 200 once the server is up."""
    return {"status": "ok"}


@app.get("/v1/status", tags=["ops"])
async def status():
    """Model readiness + GPU info."""
    h = _pipeline.health() if _pipeline else {"vllm_ready": False, "layout_ready": False}
    gpu_info = {}
    if torch.cuda.is_available():
        gpu_info = {
            "name":       torch.cuda.get_device_name(0),
            "total_mb":   torch.cuda.get_device_properties(0).total_memory // (1024**2),
            "alloc_mb":   torch.cuda.memory_allocated(0) // (1024**2),
        }
    return {**h, "gpu": gpu_info, "max_batch_size": MAX_BATCH_SIZE}


# ── OCR endpoints ─────────────────────────────────────────────────────────────

@app.post("/v1/ocr/process", response_model=OCRResult, tags=["ocr"])
async def process_single(req: OCRSingleRequest) -> OCRResult:
    """OCR a single image (base64 or URL)."""
    _require_pipeline()
    img_bytes, img_id = _resolve_image(req.image)
    return _pipeline.process_bytes(img_bytes, image_id=img_id, options=req.options)


@app.post("/v1/ocr/batch", response_model=OCRBatchResult, tags=["ocr"])
async def process_batch(req: OCRBatchRequest) -> OCRBatchResult:
    """OCR a batch of images (up to MAX_BATCH_SIZE)."""
    _require_pipeline()
    if len(req.images) > MAX_BATCH_SIZE:
        raise HTTPException(
            status_code=422,
            detail=f"Batch too large: {len(req.images)} > {MAX_BATCH_SIZE}",
        )

    sources, ids = [], []
    for inp in req.images:
        raw, img_id = _resolve_image(inp)
        sources.append(raw)
        ids.append(img_id)

    return _pipeline.batch(sources, image_ids=ids, options=req.options)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _require_pipeline():
    if _pipeline is None:
        raise HTTPException(status_code=503, detail="Pipeline not initialised yet")


def _resolve_image(inp: ImageInput) -> tuple[bytes, str]:
    """Return raw image bytes + a logical ID from an ImageInput."""
    if inp.data:
        # Caller sent base64 — strip data URI prefix if present
        b64 = inp.data.split(",", 1)[-1] if "," in inp.data else inp.data
        return base64.b64decode(b64), inp.id
    if inp.url:
        return _fetch_url(inp.url), inp.id
    raise HTTPException(status_code=422, detail=f"Image '{inp.id}': provide data or url")


def _fetch_url(url: str) -> bytes:
    if url.startswith("file://"):
        path = url[7:]
        try:
            return open(path, "rb").read()
        except OSError as e:
            raise HTTPException(status_code=422, detail=f"Cannot read file: {e}")
    if url.startswith(("http://", "https://")):
        import requests
        try:
            r = requests.get(url, timeout=15)
            r.raise_for_status()
            return r.content
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"Cannot fetch URL: {e}")
    raise HTTPException(status_code=422, detail=f"Unsupported URL scheme: {url}")


# ── Dev entrypoint ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=False)
