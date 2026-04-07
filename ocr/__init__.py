"""
OCR module public API.

Quick start::

    from ocr import OCRPipeline, OCROptions

    pipeline = OCRPipeline(vllm_url="http://localhost:8080/v1")

    # Single image
    result = pipeline.process_image("scan.jpg")
    for block in result.blocks:
        print(block.label, block.bbox_2d, block.content[:40])

    # Batch
    batch = pipeline.batch(["scan1.jpg", "scan2.jpg"])
    for r in batch.results:
        print(r.id, r.block_count, r.flagged_count)
"""

from .models   import (
    OCRBlock,
    OCRBatchResult,
    OCRBatchRequest,
    OCROptions,
    OCRResult,
    ImageInput,
)
from .pipeline import OCRPipeline
from .layout   import LayoutDetector
from .recognizer import OCRRecognizer

__all__ = [
    "OCRPipeline",
    "OCROptions",
    "OCRBlock",
    "OCRResult",
    "OCRBatchResult",
    "OCRBatchRequest",
    "ImageInput",
    "LayoutDetector",
    "OCRRecognizer",
]
