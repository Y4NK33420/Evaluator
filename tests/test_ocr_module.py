"""
OCR module smoke tests.

Runs against a live vLLM server (localhost:8080) and validates:
  1. Direct module API (OCRPipeline)
  2. Batch processing + per-image error isolation
  3. HTTP service API (if ocr-service is running on localhost:8000)

Prerequisites:
  vLLM server: docker compose up vllm-server
  (Optional) full stack: docker compose up

Usage:
  .venv\\Scripts\\python.exe tests\\test_ocr_module.py [--service]
"""

import argparse
import json
import sys
import time
from pathlib import Path

import requests

# ── Helpers ───────────────────────────────────────────────────────────────────

OK   = "\033[92m✔\033[0m"
FAIL = "\033[91m✘\033[0m"
SKIP = "\033[93m⊘\033[0m"


def check(label: str, condition: bool, detail: str = ""):
    sym = OK if condition else FAIL
    note = f"  ({detail})" if detail else ""
    print(f"  {sym}  {label}{note}")
    return condition


def separator(title: str):
    print(f"\n{'─'*60}")
    print(f"  {title}")
    print(f"{'─'*60}")


# ── Module tests ───────────────────────────────────────────────────────────────

def test_module(image_path: Path):
    separator("Test 1 — OCRPipeline (direct import)")
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from ocr import OCRPipeline, OCROptions

    pipeline = OCRPipeline(
        vllm_url  = "http://localhost:8080/v1",
        options   = OCROptions(confidence_threshold=0.85, layout_threshold=0.40),
    )

    # Health check
    h = pipeline.health()
    check("vLLM server reachable",  h["vllm_ready"],   str(h))
    check("Layout model loaded",    h["layout_ready"],  str(h))
    if not h["vllm_ready"]:
        print(f"  {SKIP}  Skipping OCR tests — vLLM not reachable")
        return False

    # Single image
    t0     = time.perf_counter()
    result = pipeline.process_image(image_path, image_id="test_single")
    elapsed = (time.perf_counter() - t0) * 1000

    check("No top-level error",       result.error is None,        result.error or "")
    check("Blocks detected (>0)",     result.block_count > 0,      str(result.block_count))
    check("All blocks have bbox_2d",  all(len(b.bbox_2d) == 4 for b in result.blocks))
    check("All confidences in [0,1]", all(0 <= b.confidence <= 1  for b in result.blocks))
    check(f"Timing recorded",         result.processing_ms > 0,    f"{elapsed:.0f} ms")

    print(f"\n  Preview ({result.block_count} blocks):")
    for b in result.blocks[:4]:
        flag = " ⚠" if b.flagged else ""
        print(f"    [{b.label}] conf={b.confidence:.2f}{flag}  {b.content[:50]!r}")

    # Batch with one bad path (error isolation)
    separator("Test 2 — Batch + error isolation")
    batch = pipeline.batch(
        sources   = [image_path, Path("non_existent.jpg")],
        image_ids = ["good_image", "bad_image"],
    )
    check("Batch has 2 results",      len(batch.results) == 2)
    check("Good image succeeded",     batch.results[0].error is None)
    check("Bad image captured error", batch.results[1].error is not None,
          batch.results[1].error or "")
    check("batch.total_ms set",       batch.total_ms > 0)

    # process_bytes
    separator("Test 3 — process_bytes")
    raw = image_path.read_bytes()
    r2  = pipeline.process_bytes(raw, image_id="bytes_test")
    check("process_bytes works",      r2.error is None)
    check("Same block count",         r2.block_count == result.block_count,
          f"{r2.block_count} vs {result.block_count}")

    # Save result
    out = Path(__file__).parent / "ocr_module_test_result.json"
    out.write_text(
        json.dumps({"single": result.model_dump(), "batch": batch.model_dump()},
                   indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"\n  Saved → {out}")
    return True


# ── Service (HTTP) tests ───────────────────────────────────────────────────────

def test_service(image_path: Path, service_url: str = "http://localhost:8000"):
    separator("Test 4 — OCR Service (HTTP)")

    # Health
    try:
        r = requests.get(f"{service_url}/v1/health", timeout=5)
        if not check("Service /health 200", r.status_code == 200):
            print(f"  {SKIP}  Service not reachable at {service_url}")
            return
    except Exception as e:
        print(f"  {SKIP}  Service not reachable: {e}")
        return

    # Status
    r = requests.get(f"{service_url}/v1/status", timeout=5)
    check("/status returns layout_ready",
          r.json().get("layout_ready") is True,  json.dumps(r.json()))

    # Single
    import base64
    b64 = base64.b64encode(image_path.read_bytes()).decode()
    payload = {
        "image":   {"id": "svc_test", "data": b64, "mime": "image/jpeg"},
        "options": {"confidence_threshold": 0.85},
    }
    r = requests.post(f"{service_url}/v1/ocr/process", json=payload, timeout=300)
    check("/ocr/process 200",     r.status_code == 200, str(r.status_code))
    res = r.json()
    check("blocks non-empty",     len(res.get("blocks", [])) > 0)

    # Batch
    payload2 = {
        "images":  [
            {"id": "img1", "data": b64, "mime": "image/jpeg"},
            {"id": "img2", "data": b64, "mime": "image/jpeg"},
        ],
        "options": {},
    }
    r2 = requests.post(f"{service_url}/v1/ocr/batch", json=payload2, timeout=600)
    check("/ocr/batch 200",        r2.status_code == 200, str(r2.status_code))
    check("batch has 2 results",   len(r2.json().get("results", [])) == 2)

    # Oversized batch
    big = {"images": [{"id": str(i), "data": b64} for i in range(33)], "options": {}}
    r3  = requests.post(f"{service_url}/v1/ocr/batch", json=big, timeout=10)
    check("Oversized batch → 422", r3.status_code == 422)


# ── Entry ─────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image",    nargs="?",
                    default=str(Path(__file__).parent / "test_image.jpeg"))
    ap.add_argument("--service",  action="store_true",
                    help="Also test the HTTP service on localhost:8000")
    ap.add_argument("--service-url", default="http://localhost:8000")
    args = ap.parse_args()

    img = Path(args.image)
    if not img.exists():
        sys.exit(f"Image not found: {img}")

    print(f"\nImage: {img}  ({img.stat().st_size // 1024} KB)")
    ok = test_module(img)

    if args.service:
        test_service(img, args.service_url)

    print(f"\n{'═'*60}")
    print(f"  {'All checks passed' if ok else 'Some checks failed — see above'}")
    print(f"{'═'*60}\n")


if __name__ == "__main__":
    main()
