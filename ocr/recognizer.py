"""
vLLM-backed OCR recogniser.

Handles per-region text extraction with:
  • logprob-based geometric-mean confidence
  • exponential-backoff retries
  • per-region timeout + fallback
"""

from __future__ import annotations

import base64
import io
import logging
import math
import time
from typing import Optional

from openai import OpenAI, APIStatusError, APITimeoutError, APIConnectionError
from PIL import Image

log = logging.getLogger(__name__)

# Prompt per task type (mirrors SDK task_prompt_mapping)
TASK_PROMPT: dict[str, str] = {
    "text":    "Text Recognition:",
    "table":   "Text Recognition:",
    "formula": "Text Recognition:",
}

_PADDING = 2          # px padding around each crop


class OCRRecognizer:
    """
    Calls the vLLM OpenAI-compat endpoint for text recognition.

    Construct one instance and reuse it across requests — it keeps an
    internal OpenAI client with connection pooling.
    """

    def __init__(
        self,
        vllm_url:    str   = "http://localhost:8080/v1",
        model_name:  str   = "glm-ocr",
        timeout:     float = 120.0,
        max_retries: int   = 3,
        max_tokens:  int   = 400,
    ):
        self._url         = vllm_url
        self._model       = model_name
        self._timeout     = timeout
        self._max_retries = max_retries
        self._max_tokens  = max_tokens
        self._client      = OpenAI(
            base_url=vllm_url,
            api_key="not-needed",
            timeout=timeout,
            max_retries=0,      # we handle retries ourselves
        )

    # ── Public API ───────────────────────────────────────────────────────────

    def recognise_region(
        self,
        img:    Image.Image,
        region: dict,
    ) -> tuple[str, float, Optional[str]]:
        """
        OCR one region crop.

        Returns (text, confidence, error_message_or_None).
        """
        crop_uri = _crop_to_data_uri(img, region["bbox_2d"])
        if crop_uri is None:
            return "", 0.5, "crop failed"

        prompt = TASK_PROMPT.get(region.get("task", "text"), "Text Recognition:")
        return self._call_with_retry(crop_uri, prompt)

    def health_check(self) -> bool:
        """Return True if the vLLM server is reachable."""
        import requests
        try:
            r = requests.get(f"{self._url}/models", timeout=5)
            return r.status_code == 200
        except Exception:
            return False

    def model_names(self) -> list[str]:
        """Return list of models served by vLLM."""
        import requests
        try:
            r = requests.get(f"{self._url}/models", timeout=5)
            return [m["id"] for m in r.json().get("data", [])]
        except Exception:
            return []

    # ── Internals ────────────────────────────────────────────────────────────

    def _call_with_retry(
        self,
        data_uri: str,
        prompt:   str,
    ) -> tuple[str, float, Optional[str]]:
        """Call vLLM with exponential backoff retries."""
        last_err: Optional[str] = None

        for attempt in range(self._max_retries):
            if attempt:
                wait = min(2 ** attempt, 16)
                log.warning("OCR retry %d/%d (wait %ds): %s",
                            attempt, self._max_retries, wait, last_err)
                time.sleep(wait)
            try:
                text, conf = self._call_once(data_uri, prompt)
                return text, conf, None
            except APITimeoutError as e:
                last_err = f"timeout: {e}"
            except APIConnectionError as e:
                last_err = f"connection: {e}"
            except APIStatusError as e:
                last_err = f"status {e.status_code}: {e.message}"
                if e.status_code < 500:
                    break   # 4xx are not retryable
            except Exception as e:
                last_err = str(e)

        log.error("OCR failed after %d retries: %s", self._max_retries, last_err)
        return "", 0.0, last_err

    def _call_once(self, data_uri: str, prompt: str) -> tuple[str, float]:
        resp = self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": data_uri}},
                {"type": "text",      "text": prompt},
            ]}],
            max_tokens=self._max_tokens,
            temperature=0.01,
            logprobs=True,
            top_logprobs=1,
        )
        text       = (resp.choices[0].message.content or "").strip()
        lp_content = resp.choices[0].logprobs.content or []
        conf       = _geometric_mean_conf(lp_content) if lp_content else 0.9
        return text, conf


# ── Helpers ──────────────────────────────────────────────────────────────────


def _crop_to_data_uri(img: Image.Image, bbox_2d: list[int]) -> Optional[str]:
    """Crop to normalised bbox and return a JPEG data URI."""
    try:
        rgb  = img.convert("RGB")
        W, H = rgb.size
        x1   = max(0, int(bbox_2d[0] * W / 1000) - _PADDING)
        y1   = max(0, int(bbox_2d[1] * H / 1000) - _PADDING)
        x2   = min(W, int(bbox_2d[2] * W / 1000) + _PADDING)
        y2   = min(H, int(bbox_2d[3] * H / 1000) + _PADDING)
        if x2 <= x1 or y2 <= y1:
            return None
        crop = rgb.crop((x1, y1, x2, y2))
        buf  = io.BytesIO()
        crop.save(buf, format="JPEG")
        b64  = base64.b64encode(buf.getvalue()).decode()
        return f"data:image/jpeg;base64,{b64}"
    except Exception as exc:
        log.warning("Crop failed: %s", exc)
        return None


def _geometric_mean_conf(lp_content) -> float:
    """Geometric mean of token probabilities → scalar confidence in [0,1]."""
    lps  = [lp.logprob for lp in lp_content]
    conf = math.exp(sum(lps) / len(lps))
    return round(max(0.0, min(1.0, conf)), 4)
