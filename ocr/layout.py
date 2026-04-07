"""
Layout detection — PP-DocLayoutV3 singleton wrapper.

Thread-safe: model is loaded once and shared across all requests.
Falls back gracefully when layout detection fails (returns a single
full-page region so OCR can still run).
"""

from __future__ import annotations

import logging
import threading
from typing import Optional

import torch
from PIL import Image

log = logging.getLogger(__name__)

# PP-DocLayoutV3 HuggingFace model ID (safetensors variant)
_LAYOUT_MODEL_ID = "PaddlePaddle/PP-DocLayoutV3_safetensors"

# Map layout labels → OCR task type (or "skip")
LABEL_TASK: dict[str, str] = {
    "text": "text", "title": "text", "paragraph": "text",
    "list": "text", "list_item": "text",
    "table": "table", "table_caption": "text",
    "formula": "formula",
    "figure": "skip", "figure_caption": "text",
    "page-header": "skip", "page-footer": "skip",
    "header": "skip", "footer": "skip",
    "abandon": "skip", "background": "skip",
}


class LayoutDetector:
    """Singleton PP-DocLayoutV3 wrapper. Load once, call process() many times."""

    _instance: Optional["LayoutDetector"] = None
    _lock = threading.Lock()

    def __init__(self, model_id: str = _LAYOUT_MODEL_ID, threshold: float = 0.40):
        self._model_id  = model_id
        self._threshold = threshold
        self._model     = None
        self._processor = None
        self._id2label: dict[int, str] = {}
        self._ready     = False

    # ── Singleton factory ────────────────────────────────────────────────────

    @classmethod
    def get(cls, model_id: str = _LAYOUT_MODEL_ID, threshold: float = 0.40) -> "LayoutDetector":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls(model_id, threshold)
                cls._instance._load()
            return cls._instance

    # ── Internals ────────────────────────────────────────────────────────────

    def _load(self) -> None:
        from transformers import (
            PPDocLayoutV3ForObjectDetection,
            PPDocLayoutV3ImageProcessor,
        )
        log.info("Loading PP-DocLayoutV3 from '%s' ...", self._model_id)
        self._processor = PPDocLayoutV3ImageProcessor.from_pretrained(self._model_id)
        self._model     = PPDocLayoutV3ForObjectDetection.from_pretrained(self._model_id)
        self._model.eval()
        self._id2label  = self._model.config.id2label
        self._ready     = True
        log.info("PP-DocLayoutV3 ready (%d classes)", len(self._id2label))

    @property
    def ready(self) -> bool:
        return self._ready

    # ── Public API ───────────────────────────────────────────────────────────

    def process(self, img: Image.Image) -> list[dict]:
        """
        Detect layout regions in *img*.

        Returns a list of region dicts sorted in reading order:
            {label, task, score, bbox_2d: [x1,y1,x2,y2] (0-1000), index}
        On failure returns a single full-page fallback region.
        """
        if not self._ready:
            log.warning("Layout detector not loaded — returning full-page fallback")
            return _full_page_region()

        try:
            return self._run(img)
        except Exception as exc:
            log.error("Layout detection failed (%s) — full-page fallback", exc)
            return _full_page_region()

    def _run(self, img: Image.Image) -> list[dict]:
        img_rgb = img.convert("RGB")
        W, H    = img_rgb.size

        inputs  = self._processor(images=[img_rgb], return_tensors="pt")
        with torch.no_grad():
            outputs = self._model(**inputs)

        target  = torch.tensor([[H, W]])
        results = self._processor.post_process_object_detection(
            outputs,
            threshold=self._threshold,
            target_sizes=target,
        )[0]

        regions = []
        for score, label_id, box in zip(
            results["scores"], results["labels"], results["boxes"]
        ):
            label_name = self._id2label.get(int(label_id), "text")
            task       = LABEL_TASK.get(label_name, "text")
            if task == "skip":
                continue
            x1, y1, x2, y2 = box.tolist()
            regions.append({
                "label":   label_name,
                "task":    task,
                "score":   round(float(score), 4),
                "bbox_2d": [
                    int(x1 * 1000 / W), int(y1 * 1000 / H),
                    int(x2 * 1000 / W), int(y2 * 1000 / H),
                ],
            })

        # Reading order: top-to-bottom, left-to-right
        regions.sort(key=lambda r: (r["bbox_2d"][1], r["bbox_2d"][0]))
        for i, r in enumerate(regions):
            r["index"] = i

        if not regions:
            log.warning("No regions detected — returning full-page fallback")
            return _full_page_region()

        return regions


def _full_page_region() -> list[dict]:
    """Fallback: treat entire image as one text region."""
    return [{"label": "text", "task": "text", "score": 0.0,
             "bbox_2d": [0, 0, 1000, 1000], "index": 0}]
