"""
OCRPipeline — high-level orchestrator.

Combines PP-DocLayoutV3 (layout) + vLLM GLM-OCR (text recognition)
into a simple, batch-capable interface.

Design decisions
----------------
* Images in a batch are processed **sequentially** to avoid saturating the
  shared GPU KV-cache on a 4 GB card.
* Regions within a single image are processed sequentially too (cheap crop
  + one GPU slot at a time = stable latency).
* Each image's failure is isolated — one bad image never breaks the rest.
* Layout detection failure falls back to full-page OCR automatically.
"""

from __future__ import annotations

import base64
import io
import logging
import time
from pathlib import Path
from typing import Optional, Union

from PIL import Image

from .layout     import LayoutDetector
from .models     import OCRBlock, OCRBatchResult, OCROptions, OCRResult
from .recognizer import OCRRecognizer

log = logging.getLogger(__name__)


class OCRPipeline:
    """
    Main interface for the OCR module.

    Usage::

        pipeline = OCRPipeline(vllm_url="http://localhost:8080/v1")

        result  = pipeline.process_image("scan.jpg")
        results = pipeline.batch(["scan1.jpg", "scan2.jpg"])

        with open("scan.jpg", "rb") as f:
            result = pipeline.process_bytes(f.read(), image_id="student_001")
    """

    def __init__(
        self,
        vllm_url:    str         = "http://localhost:8080/v1",
        model_name:  str         = "glm-ocr",
        layout_model: str        = "PaddlePaddle/PP-DocLayoutV3_safetensors",
        options:     OCROptions  = None,
        preload_layout: bool     = True,
    ):
        self._options    = options or OCROptions()
        self._recognizer = OCRRecognizer(
            vllm_url    = vllm_url,
            model_name  = model_name,
            timeout     = 120.0,
            max_retries = self._options.ocr_retries,
            max_tokens  = self._options.max_tokens_per_region,
        )
        # Layout detector is a singleton — loaded once across all instances
        if preload_layout:
            self._layout = LayoutDetector.get(
                model_id  = layout_model,
                threshold = self._options.layout_threshold,
            )
        else:
            self._layout = None

    # ── Public batch API ─────────────────────────────────────────────────────

    def batch(
        self,
        sources: list[Union[str, Path, bytes]],
        image_ids: Optional[list[str]] = None,
        options:   Optional[OCROptions] = None,
    ) -> OCRBatchResult:
        """
        Process a list of images (paths, bytes, or base64 strings).

        Returns an OCRBatchResult with one OCRResult per input.
        Failures are captured per-image; the batch never raises.
        """
        opts     = options or self._options
        ids      = image_ids or [str(i) for i in range(len(sources))]
        t0       = time.perf_counter()
        results  = []

        for src, img_id in zip(sources, ids):
            result = self._process_one(src, img_id, opts)
            results.append(result)

        total_ms = (time.perf_counter() - t0) * 1000
        log.info("Batch of %d images done in %.0f ms", len(sources), total_ms)
        return OCRBatchResult(results=results, total_ms=round(total_ms, 1))

    # ── Convenience single-image methods ─────────────────────────────────────

    def process_image(
        self,
        path:     Union[str, Path],
        image_id: Optional[str] = None,
        options:  Optional[OCROptions] = None,
    ) -> OCRResult:
        """Process a single image from a file path."""
        img_id = image_id or Path(path).name
        return self._process_one(path, img_id, options or self._options)

    def process_bytes(
        self,
        data:     bytes,
        image_id: str   = "image",
        mime:     str   = "image/jpeg",
        options:  Optional[OCROptions] = None,
    ) -> OCRResult:
        """Process a single image from raw bytes."""
        return self._process_one(data, image_id, options or self._options)

    def process_base64(
        self,
        b64:      str,
        image_id: str  = "image",
        mime:     str  = "image/jpeg",
        options:  Optional[OCROptions] = None,
    ) -> OCRResult:
        """Process a single image from a base64 string."""
        data = base64.b64decode(b64)
        return self.process_bytes(data, image_id, mime, options)

    # ── Status ────────────────────────────────────────────────────────────────

    def health(self) -> dict:
        return {
            "vllm_ready":   self._recognizer.health_check(),
            "layout_ready": self._layout is not None and self._layout.ready,
            "vllm_models":  self._recognizer.model_names(),
        }

    # ── Internal ─────────────────────────────────────────────────────────────

    def _process_one(
        self,
        source:  Union[str, Path, bytes],
        img_id:  str,
        opts:    OCROptions,
    ) -> OCRResult:
        t0 = time.perf_counter()
        try:
            img    = _load_image(source)
            layout = self._layout or LayoutDetector.get()
            regions = layout.process(img)
            blocks  = self._run_ocr(img, regions, opts)
        except Exception as exc:
            ms = (time.perf_counter() - t0) * 1000
            log.error("Image '%s' failed: %s", img_id, exc)
            return OCRResult(
                id=img_id,
                error=str(exc),
                processing_ms=round(ms, 1),
            )

        flagged = sum(1 for b in blocks if b.flagged)
        ms      = (time.perf_counter() - t0) * 1000
        log.info("Image '%s': %d blocks, %d flagged, %.0f ms",
                 img_id, len(blocks), flagged, ms)
        return OCRResult(
            id=img_id,
            blocks=blocks,
            block_count=len(blocks),
            flagged_count=flagged,
            processing_ms=round(ms, 1),
        )

    def _run_ocr(
        self,
        img:     Image.Image,
        regions: list[dict],
        opts:    OCROptions,
    ) -> list[OCRBlock]:
        blocks = []
        for region in regions:
            text, conf, err = self._recognizer.recognise_region(img, region)
            blocks.append(OCRBlock(
                index      = region["index"],
                label      = region["label"],
                content    = text,
                bbox_2d    = region["bbox_2d"],
                confidence = conf,
                flagged    = conf < opts.confidence_threshold,
                error      = err,
            ))
        return blocks


# ── Image loader ─────────────────────────────────────────────────────────────


def _load_image(source: Union[str, Path, bytes]) -> Image.Image:
    if isinstance(source, bytes):
        return Image.open(io.BytesIO(source)).convert("RGB")
    path = Path(source)
    if path.exists():
        return Image.open(path).convert("RGB")
    raise FileNotFoundError(f"Image not found: {source}")
