"""Image preprocessor: rotation detection + SHA-256 deduplication."""

import hashlib
import logging
from pathlib import Path

from PIL import Image

log = logging.getLogger(__name__)

_ROTATION_THRESHOLD = 5.0   # degrees; rotate only if |angle| > this


def preprocess_image(path: Path) -> tuple[Path, str]:
    """
    1. Compute SHA-256 hash (for deduplication by caller).
    2. Detect and correct page rotation (Tesseract OSD; falls back gracefully).
    3. Save corrected image in-place and return (path, sha256_hex).
    """
    raw = path.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()

    try:
        img     = Image.open(path).convert("RGB")
        rotated = _auto_rotate(img)
        if rotated is not img:
            rotated.save(path, format="JPEG", quality=95)
            log.info("Auto-rotated %s", path.name)
    except Exception as exc:
        log.warning("Rotation detection skipped for %s: %s", path.name, exc)

    return path, sha


def _auto_rotate(img: Image.Image) -> Image.Image:
    """Detect rotation via pytesseract OSD and correct it."""
    try:
        import pytesseract
        osd = pytesseract.image_to_osd(img, output_type=pytesseract.Output.DICT)
        angle = float(osd.get("rotate", 0))
        if abs(angle) > _ROTATION_THRESHOLD:
            log.debug("Rotating by %.1f°", angle)
            return img.rotate(angle, expand=True)
        return img
    except Exception:
        # Tesseract not installed or OSD failed — try OpenCV Hough
        return _hough_rotate(img)


def _hough_rotate(img: Image.Image) -> Image.Image:
    """Lightweight Hough-Transform rotation estimate via OpenCV."""
    try:
        import cv2
        import numpy as np
        gray  = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2GRAY)
        edges = cv2.Canny(gray, 50, 150, apertureSize=3)
        lines = cv2.HoughLines(edges, 1, np.pi / 180, 200)
        if lines is None:
            return img
        angles = []
        for rho, theta in lines[:, 0]:
            deg = np.degrees(theta) - 90
            if abs(deg) < 45:
                angles.append(deg)
        if not angles:
            return img
        median = float(np.median(angles))
        if abs(median) > _ROTATION_THRESHOLD:
            return img.rotate(-median, expand=True)
        return img
    except Exception:
        return img
