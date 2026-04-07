"""
GLM-OCR Pipeline Test — bbox + text + confidence
================================================
Bypasses glmocr SDK (multiple bugs in 0.1.4).
Uses the same components the SDK uses internally:

  Phase 1: PP-DocLayoutV3 (CPU, transformers)
           → detects text/table/formula regions with bbox_2d

  Phase 2: vLLM (localhost:8080) "Text Recognition:"
           → OCR text per cropped region (with logprobs for confidence)

  Output:  tests/ocr_sdk_result.json
           [{index, label, content, bbox_2d, confidence, flagged}]

Prerequisites:
  Start server:  .\\tests\\start_vllm_server.ps1
  Run:  .venv\\Scripts\\python.exe tests\\ocr_sdk_test.py [image_path]
"""

import sys
import json
import math
import time
import base64
import io
from pathlib import Path

import torch
import numpy as np
import requests
from PIL import Image
from openai import OpenAI
from transformers import (
    PPDocLayoutV3ForObjectDetection,
    PPDocLayoutV3ImageProcessorFast,
)

# ── Config ─────────────────────────────────────────────────────────────────
VLLM_BASE_URL         = "http://localhost:8080/v1"
VLLM_MODEL_NAME       = "glm-ocr"
LAYOUT_MODEL_ID       = "PaddlePaddle/PP-DocLayoutV3_safetensors"
CONFIDENCE_THRESHOLD  = 0.85
LAYOUT_THRESHOLD      = 0.40          # minimum detection score
OUTPUT_FILE           = Path(__file__).parent / "ocr_sdk_result.json"

# Map PP-DocLayoutV3 label groups → OCR task (or "skip")
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

# Text prompt per task type (same as SDK task_prompt_mapping)
TASK_PROMPT: dict[str, str] = {
    "text":    "Text Recognition:",
    "table":   "Text Recognition:",
    "formula": "Text Recognition:",
}


def find_test_image() -> Path:
    tests_dir = Path(__file__).parent
    for ext in ("*.jpeg", "*.jpg", "*.png", "*.webp"):
        matches = [p for p in tests_dir.glob(ext) if "result" not in p.stem]
        if matches:
            return matches[0]
    raise FileNotFoundError("No test image found in tests/")


def wait_for_server(timeout: int = 30) -> bool:
    print(f"Checking vLLM server at {VLLM_BASE_URL} ...")
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = requests.get(f"{VLLM_BASE_URL}/models", timeout=3)
            if r.status_code == 200:
                models = [m["id"] for m in r.json().get("data", [])]
                print(f"✅ Server ready. Models: {models}")
                return True
        except Exception:
            pass
        time.sleep(2)
    return False


# ── Phase 1: Layout Detection ───────────────────────────────────────────────

def detect_layout(image_path: Path) -> list[dict]:
    """
    Run PP-DocLayoutV3 on the full image.
    Returns list of {label, bbox_2d (0-1000 normalised), score} dicts.
    """
    print(f"  Loading PP-DocLayoutV3 from '{LAYOUT_MODEL_ID}' (CPU) ...")
    processor = PPDocLayoutV3ImageProcessorFast.from_pretrained(LAYOUT_MODEL_ID)
    model = PPDocLayoutV3ForObjectDetection.from_pretrained(LAYOUT_MODEL_ID)
    model.eval()

    img = Image.open(image_path).convert("RGB")
    W, H = img.size

    inputs = processor(images=[img], return_tensors="pt")
    with torch.no_grad():
        outputs = model(**inputs)

    target = torch.tensor([[H, W]])
    results = processor.post_process_object_detection(
        outputs,
        threshold=LAYOUT_THRESHOLD,
        target_sizes=target,
    )[0]

    id2label = model.config.id2label
    regions = []
    for score, label_id, box in zip(
        results["scores"], results["labels"], results["boxes"]
    ):
        label_name = id2label.get(int(label_id), "text")
        task = LABEL_TASK.get(label_name, "text")
        if task == "skip":
            continue
        x1, y1, x2, y2 = box.tolist()
        regions.append({
            "label": label_name,
            "task":  task,
            "score": round(float(score), 4),
            "bbox_2d": [
                int(x1 * 1000 / W), int(y1 * 1000 / H),
                int(x2 * 1000 / W), int(y2 * 1000 / H),
            ],
        })

    # Sort top-to-bottom, left-to-right (reading order)
    regions.sort(key=lambda r: (r["bbox_2d"][1], r["bbox_2d"][0]))
    for i, r in enumerate(regions):
        r["index"] = i

    print(f"  → {len(regions)} regions detected (skipped figure/header/footer)")
    return regions


# ── Phase 2: Per-region OCR via vLLM ───────────────────────────────────────

def crop_to_b64(image_path: Path, bbox_2d: list[int]) -> str | None:
    """Crop image region by normalised 0-1000 coords, return JPEG base64 data URI."""
    try:
        img = Image.open(image_path).convert("RGB")
        W, H = img.size
        x1, y1, x2, y2 = (
            max(0, int(bbox_2d[0] * W / 1000) - 2),
            max(0, int(bbox_2d[1] * H / 1000) - 2),
            min(W, int(bbox_2d[2] * W / 1000) + 2),
            min(H, int(bbox_2d[3] * H / 1000) + 2),
        )
        if x2 <= x1 or y2 <= y1:
            return None
        crop = img.crop((x1, y1, x2, y2))
        buf = io.BytesIO()
        crop.save(buf, format="JPEG")
        b64 = base64.b64encode(buf.getvalue()).decode()
        return f"data:image/jpeg;base64,{b64}"
    except Exception:
        return None


def ocr_region(
    client: OpenAI,
    image_path: Path,
    region: dict,
) -> tuple[str, float]:
    """
    OCR one region via vLLM with logprobs.
    Returns (text, confidence).
    """
    data_uri = crop_to_b64(image_path, region["bbox_2d"])
    if data_uri is None:
        return "", 0.90

    prompt = TASK_PROMPT.get(region["task"], "Text Recognition:")
    try:
        resp = client.chat.completions.create(
            model=VLLM_MODEL_NAME,
            messages=[{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": data_uri}},
                {"type": "text", "text": prompt},
            ]}],
            max_tokens=400,
            temperature=0.01,
            logprobs=True,
            top_logprobs=1,
        )
        text = (resp.choices[0].message.content or "").strip()
        lp_content = resp.choices[0].logprobs.content or []
        if lp_content:
            lps = [lp.logprob for lp in lp_content]
            conf = math.exp(sum(lps) / len(lps))
        else:
            conf = 0.90
        return text, round(conf, 4)
    except Exception as e:
        return f"[OCR ERROR: {e}]", 0.50


# ── Main ────────────────────────────────────────────────────────────────────

def print_summary(blocks: list[dict], image_path: Path):
    flagged = [b for b in blocks if b.get("flagged")]
    has_bbox = sum(1 for b in blocks if b.get("bbox_2d"))

    print("\n" + "=" * 75)
    print("GLM-OCR PIPELINE RESULT SUMMARY")
    print("=" * 75)
    print(f"Image   : {image_path.name}")
    print(f"Blocks  : {len(blocks)}  |  With bbox_2d: {has_bbox}  |  Flagged: {len(flagged)}")
    print()
    print(f"{'#':<4} {'Label':<14} {'Conf':<7} {'F':<2} {'bbox_2d':<28} Content")
    print("-" * 80)
    for b in blocks:
        bbox = str(b.get("bbox_2d", ""))[:26]
        flag = "⚠" if b.get("flagged") else " "
        preview = (b.get("content") or "")[:35].replace("\n", " ")
        print(f"{b.get('index','?')!s:<4} {b.get('label','text'):<14} {b.get('confidence',0):<7} {flag:<2} {bbox:<28} {preview}")

    if flagged:
        print(f"\n--- ⚠ Low-Confidence (< {CONFIDENCE_THRESHOLD}) ---")
        for b in flagged:
            print(f"  [{b['confidence']:.3f}] bbox={b.get('bbox_2d')}  {(b.get('content') or '')[:60]}")

    print(f"\nSaved → {OUTPUT_FILE}")


def main():
    image_path = Path(sys.argv[1]) if len(sys.argv) > 1 else find_test_image()
    if not image_path.exists():
        print(f"ERROR: {image_path} not found")
        sys.exit(1)

    print(f"Image : {image_path}\n")

    if not wait_for_server():
        sys.exit("ERROR: vLLM not responding. Run .\\tests\\start_vllm_server.ps1")

    client = OpenAI(base_url=VLLM_BASE_URL, api_key="not-needed", timeout=120.0)

    # ── Phase 1 ─────────────────────────────────────────────────────────────
    print("\n[Phase 1/2] Layout detection (PP-DocLayoutV3, CPU) ...")
    regions = detect_layout(image_path)

    if not regions:
        sys.exit("⚠  No regions detected by layout model.")

    # ── Phase 2 ─────────────────────────────────────────────────────────────
    print(f"\n[Phase 2/2] OCR per region via vLLM ({len(regions)} regions) ...")
    blocks = []
    for i, region in enumerate(regions):
        text, conf = ocr_region(client, image_path, region)
        blocks.append({
            "index":      region["index"],
            "label":      region["label"],
            "score":      region["score"],
            "content":    text,
            "bbox_2d":    region["bbox_2d"],
            "confidence": conf,
            "flagged":    conf < CONFIDENCE_THRESHOLD,
        })
        print(f"  [{i+1}/{len(regions)}] {region['label']:12s} conf={conf:.2f}  {text[:40]!r}")

    print_summary(blocks, image_path)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump({
            "image":         str(image_path),
            "layout_model":  LAYOUT_MODEL_ID,
            "ocr_model":     VLLM_MODEL_NAME,
            "block_count":   len(blocks),
            "flagged_count": sum(1 for b in blocks if b["flagged"]),
            "blocks":        blocks,
        }, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    main()
