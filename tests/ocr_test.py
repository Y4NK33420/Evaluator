"""
GLM-OCR Prototype Test
======================
Loads zai-org/GLM-OCR using HuggingFace Transformers with 4-bit BitsAndBytes
quantization so it fits within 4 GB of VRAM.

Usage:
    python ocr_test.py <image_path>
    python ocr_test.py                   # auto-picks first image in tests/

Outputs:
    - Raw OCR text (printed to console)
    - JSON file: ocr_result.json  (text + per-block confidence scores)
"""

import sys
import json
import math
import os
from pathlib import Path

import torch
from PIL import Image
from transformers import (
    AutoProcessor,
    AutoModelForImageTextToText,
    BitsAndBytesConfig,
)

# ── Config ─────────────────────────────────────────────────────────────────
MODEL_PATH = "zai-org/GLM-OCR"
CONFIDENCE_THRESHOLD = 0.85          # flag text blocks below this
MAX_NEW_TOKENS = 8192
OUTPUT_FILE = Path(__file__).parent / "ocr_result.json"

# BitsAndBytes 4-bit quantization to fit in 4 GB VRAM
BNB_CONFIG = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_quant_type="nf4",
    bnb_4bit_use_double_quant=True,
    bnb_4bit_compute_dtype=torch.float16,
)


def find_test_image() -> Path:
    """Auto-discover first image in the tests/ directory."""
    tests_dir = Path(__file__).parent
    for ext in ("*.png", "*.jpg", "*.jpeg", "*.webp", "*.tiff", "*.bmp"):
        matches = [p for p in tests_dir.glob(ext) if p.name != "ocr_result.json"]
        if matches:
            return matches[0]
    raise FileNotFoundError(
        "No image found in tests/. Place a scanned marksheet image there and re-run."
    )


def load_model():
    print(f"[1/3] Loading processor from {MODEL_PATH} ...")
    processor = AutoProcessor.from_pretrained(MODEL_PATH)

    print(f"[2/3] Loading model (4-bit quantized) ...")
    model = AutoModelForImageTextToText.from_pretrained(
        pretrained_model_name_or_path=MODEL_PATH,
        quantization_config=BNB_CONFIG,
        device_map="auto",          # handles multi-GPU / CPU offload automatically
        torch_dtype=torch.float16,
    )
    model.eval()
    return processor, model


def run_ocr(image_path: Path, processor, model) -> dict:
    """
    Run GLM-OCR on a single image.
    Returns a dict with:
        - text: full raw OCR string
        - tokens: list of {token, logprob}
        - blocks: lines with per-line confidence (geometric mean of token logprobs)
        - flagged_blocks: lines below CONFIDENCE_THRESHOLD
    """
    print(f"[3/3] Running OCR on: {image_path.name}")

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "image", "url": str(image_path)},
                {"type": "text", "text": "Text Recognition:"},
            ],
        }
    ]

    inputs = processor.apply_chat_template(
        messages,
        tokenize=True,
        add_generation_prompt=True,
        return_dict=True,
        return_tensors="pt",
    ).to(model.device)
    inputs.pop("token_type_ids", None)

    with torch.no_grad():
        output = model.generate(
            **inputs,
            max_new_tokens=MAX_NEW_TOKENS,
            return_dict_in_generate=True,
            output_scores=True,          # gives us per-step logits
        )

    # ── Decode text ───────────────────────────────────────────────────────
    generated_ids = output.sequences[0][inputs["input_ids"].shape[1]:]
    raw_text = processor.decode(generated_ids, skip_special_tokens=False)

    # ── Extract per-token log-probs ───────────────────────────────────────
    # output.scores is a tuple of (vocab_size,) tensors, one per generated step
    token_logprobs = []
    token_strings = []
    for step_idx, (tok_id, score_tensor) in enumerate(
        zip(generated_ids.tolist(), output.scores)
    ):
        logprob = torch.log_softmax(score_tensor[0], dim=-1)[tok_id].item()
        token_text = processor.tokenizer.decode([tok_id])
        token_logprobs.append(logprob)
        token_strings.append(token_text)

    # ── Compute per-line confidence (geometric mean) ──────────────────────
    lines = raw_text.split("\n")
    blocks = []
    token_cursor = 0

    for line in lines:
        if not line.strip():
            continue

        # greedily assign tokens to this line
        line_logprobs = []
        chars_accounted = 0
        while token_cursor < len(token_strings) and chars_accounted < len(line):
            lp = token_logprobs[token_cursor]
            line_logprobs.append(lp)
            chars_accounted += len(token_strings[token_cursor])
            token_cursor += 1

        if line_logprobs:
            geo_mean = math.exp(sum(line_logprobs) / len(line_logprobs))
        else:
            geo_mean = 1.0

        blocks.append(
            {
                "text": line,
                "confidence": round(geo_mean, 4),
                "flagged": geo_mean < CONFIDENCE_THRESHOLD,
            }
        )

    return {
        "image": str(image_path),
        "raw_text": raw_text,
        "token_count": len(token_logprobs),
        "blocks": blocks,
        "flagged_blocks": [b for b in blocks if b["flagged"]],
    }


def print_summary(result: dict):
    print("\n" + "=" * 60)
    print("OCR RESULT SUMMARY")
    print("=" * 60)
    print(f"Image      : {Path(result['image']).name}")
    print(f"Tokens gen : {result['token_count']}")
    print(f"Lines found: {len(result['blocks'])}")
    print(f"Flagged    : {len(result['flagged_blocks'])} lines < {CONFIDENCE_THRESHOLD} confidence")
    print("\n--- Extracted Text ---")
    print(result["raw_text"])

    if result["flagged_blocks"]:
        print("\n--- ⚠ Low-Confidence Lines ---")
        for b in result["flagged_blocks"]:
            print(f"  [{b['confidence']:.3f}] {b['text']}")

    print(f"\nFull result saved to: {OUTPUT_FILE}")


def main():
    # resolve image path
    if len(sys.argv) > 1:
        image_path = Path(sys.argv[1])
        if not image_path.exists():
            print(f"ERROR: File not found: {image_path}")
            sys.exit(1)
    else:
        image_path = find_test_image()
        print(f"Auto-detected test image: {image_path}")

    # sanity check GPU
    if torch.cuda.is_available():
        gpu = torch.cuda.get_device_properties(0)
        print(f"GPU: {gpu.name} ({gpu.total_memory // 1024**2} MB VRAM)")
    else:
        print("⚠  No CUDA GPU detected — running on CPU (will be slow).")

    processor, model = load_model()
    result = run_ocr(image_path, processor, model)

    print_summary(result)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    main()
