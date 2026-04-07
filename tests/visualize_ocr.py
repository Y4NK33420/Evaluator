"""
Visualize OCR bounding boxes on the original image.
Usage: .venv\\Scripts\\python.exe tests\\visualize_ocr.py
"""

import json
import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

RESULT_FILE = Path(__file__).parent / "ocr_sdk_result.json"
OUTPUT_FILE = Path(__file__).parent / "ocr_visualization.png"

# Colour scheme: label → (box_colour, text_bg)
LABEL_COLOURS = {
    "text":    ("#2196F3", "#1565C0"),   # blue
    "formula": ("#9C27B0", "#6A0DAD"),   # purple
    "table":   ("#4CAF50", "#2E7D32"),   # green
    "title":   ("#FF9800", "#E65100"),   # orange
    "figure":  ("#9E9E9E", "#616161"),   # grey
}
DEFAULT_COLOUR = ("#F44336", "#B71C1C")  # red fallback

FLAG_COLOUR   = "#FF1744"   # red tint for flagged blocks
FONT_SIZE     = 14
LINE_WIDTH    = 2


def get_font(size: int):
    for name in ["arial.ttf", "Arial.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf"]:
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            pass
    return ImageFont.load_default()


def denorm(val: int, dim: int) -> int:
    return int(val * dim / 1000)


def main():
    result_file = Path(sys.argv[1]) if len(sys.argv) > 1 else RESULT_FILE
    data = json.loads(result_file.read_text(encoding="utf-8"))

    image_path = Path(data["image"])
    if not image_path.exists():
        # Try relative to result file dir
        image_path = result_file.parent / image_path.name
    img = Image.open(image_path).convert("RGB")
    W, H = img.size

    draw = ImageDraw.Draw(img, "RGBA")
    font      = get_font(FONT_SIZE)
    font_sm   = get_font(FONT_SIZE - 2)

    blocks = data.get("blocks", [])
    print(f"Visualising {len(blocks)} blocks on {image_path.name} ({W}×{H})")

    for block in blocks:
        bbox = block.get("bbox_2d")
        if not bbox or len(bbox) != 4:
            continue
        x1 = denorm(bbox[0], W)
        y1 = denorm(bbox[1], H)
        x2 = denorm(bbox[2], W)
        y2 = denorm(bbox[3], H)

        label   = block.get("label", "text")
        conf    = block.get("confidence", 0.0)
        flagged = block.get("flagged", False)
        content = (block.get("content") or "").replace("\n", " ").strip()

        box_colour, text_bg = LABEL_COLOURS.get(label, DEFAULT_COLOUR)
        if flagged:
            box_colour = FLAG_COLOUR   # override to red for flagged
            text_bg    = "#C62828"

        # Translucent fill
        draw.rectangle(
            [x1, y1, x2, y2],
            fill=(*[int(box_colour.lstrip("#")[i:i+2], 16) for i in (0, 2, 4)], 35),
            outline=box_colour,
            width=LINE_WIDTH,
        )

        # Label tag at top-left of box
        tag = f"#{block.get('index','')} {label} {conf:.2f}"
        try:
            tw = draw.textlength(tag, font=font_sm)
        except AttributeError:
            tw = len(tag) * (FONT_SIZE - 2) * 0.6
        th = FONT_SIZE
        tag_y = max(0, y1 - th - 4)
        draw.rectangle(
            [x1, tag_y, x1 + tw + 8, tag_y + th + 4],
            fill=(*[int(text_bg.lstrip("#")[i:i+2], 16) for i in (0, 2, 4)], 200),
        )
        draw.text((x1 + 4, tag_y + 2), tag, fill="white", font=font_sm)

        # Content preview inside box (first 55 chars)
        preview = content[:55] + ("…" if len(content) > 55 else "")
        if preview:
            draw.text((x1 + 4, y1 + 4), preview, fill="white", font=font, stroke_width=1, stroke_fill="black")

    img.save(OUTPUT_FILE)
    print(f"✅ Saved → {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
