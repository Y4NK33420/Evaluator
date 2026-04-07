# OCR Module

GLM-OCR 0.9B + PP-DocLayoutV3 pipeline — bounding boxes, text, confidence.

## Quick start (Docker)

```bash
cp .env.example .env          # optionally add HF_TOKEN

docker compose up -d          # starts vllm-server (GPU) + ocr-service (CPU)
docker compose logs -f        # watch startup (first run downloads ~3 GB, ~8 min)
```

Note: this repo now builds a custom `vllm-server` image with pinned Transformers.
The first `docker compose up` may take longer because image build happens once,
but container restarts avoid repeated apt/pip installs.

Once both services show healthy:

```bash
# Single image via HTTP
curl -s -X POST http://localhost:8000/v1/ocr/process \
  -H "Content-Type: application/json" \
  -d '{
    "image": {"id": "test", "url": "file:///absolute/path/to/scan.jpg"},
    "options": {"confidence_threshold": 0.85}
  }' | python -m json.tool
```

## Direct Python API (no Docker)

```python
from ocr import OCRPipeline, OCROptions

pipeline = OCRPipeline(vllm_url="http://localhost:8080/v1")

# Single image
result = pipeline.process_image("scan.jpg")
for block in result.blocks:
    print(f"[{block.label}] conf={block.confidence:.2f}  {block.content[:60]}")

# Batch (sequential, safe for 4 GB GPU)
batch = pipeline.batch(["page1.jpg", "page2.jpg", "page3.jpg"])
for r in batch.results:
    print(r.id, r.block_count, "blocks,", r.flagged_count, "flagged")
```

## Response schema

```jsonc
{
  "id": "student_001",
  "blocks": [
    {
      "index": 0,
      "label": "text",           // text | title | formula | table | figure
      "content": "Shannon Channel Capacity",
      "bbox_2d": [60, 13, 509, 54],   // [x1,y1,x2,y2] in 0-1000 (normalised)
      "confidence": 0.93,
      "flagged": false,          // true when confidence < threshold (0.85)
      "error": null
    }
  ],
  "block_count": 17,
  "flagged_count": 3,
  "processing_ms": 4120,
  "error": null                  // set only if the entire image failed
}
```

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/v1/health` | Liveness probe |
| GET | `/v1/status` | Layout + vLLM readiness, GPU info |
| POST | `/v1/ocr/process` | Single image |
| POST | `/v1/ocr/batch` | Up to 32 images |

## Error handling

| Situation | Behaviour |
|-----------|-----------|
| vLLM region timeout | Retry ×3 (exp backoff); block gets `flagged=true, error="timeout"` |
| Layout detection failure | Falls back to full-page OCR automatically |
| One bad image in batch | `result.error` set for that image; rest of batch continues |
| vLLM server down | `503` from `ocr-service` |

## Smoke test

```bash
# Tests direct module API + batch isolation
.venv\Scripts\python.exe tests\test_ocr_module.py tests\test_image.jpeg

# Also tests the HTTP service
.venv\Scripts\python.exe tests\test_ocr_module.py tests\test_image.jpeg --service
```

## Architecture

```
Main App
  → POST http://ocr-service:8000/v1/ocr/batch   (JSON + base64)
        ↓
  ocr-service  (CPU)
    PP-DocLayoutV3  →  region bboxes
    for each region:
      → POST vllm-server:8080  (cropped JPEG + "Text Recognition:")
             ↓
      GLM-OCR 0.9B  →  text + logprobs
    confidence = exp(mean(logprobs))
        ↓
  Returns OCRBatchResult
```
