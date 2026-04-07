"""Utilities for parsing LLM JSON output robustly."""

from __future__ import annotations

import json
import re


def _strip_code_fences(text: str) -> str:
    s = text.strip()
    if s.startswith("```"):
        # Remove opening fence with optional language tag.
        s = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", s)
        # Remove trailing fence.
        s = re.sub(r"\s*```$", "", s)
    return s.strip()


def _extract_outer_json_object(text: str) -> str | None:
    start = text.find("{")
    if start == -1:
        return None

    depth = 0
    in_string = False
    escaped = False

    for i, ch in enumerate(text[start:], start=start):
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]

    return None


def _remove_trailing_commas(text: str) -> str:
    # Best-effort cleanup for common LLM JSON issue.
    return re.sub(r",\s*([}\]])", r"\1", text)


def robust_json_loads(text: str) -> dict:
    """
    Parse potentially messy LLM JSON output.

    Tries, in order:
      1) direct JSON parse
      2) parse after stripping markdown code fences
      3) parse extracted outer JSON object from raw text
      4) parse extracted object after trailing-comma cleanup
    """
    candidates: list[str] = []

    raw = text.strip()
    if raw:
        candidates.append(raw)

    fenced = _strip_code_fences(raw)
    if fenced and fenced not in candidates:
        candidates.append(fenced)

    extracted_raw = _extract_outer_json_object(raw)
    if extracted_raw and extracted_raw not in candidates:
        candidates.append(extracted_raw)

    extracted_fenced = _extract_outer_json_object(fenced)
    if extracted_fenced and extracted_fenced not in candidates:
        candidates.append(extracted_fenced)

    for candidate in list(candidates):
        cleaned = _remove_trailing_commas(candidate)
        if cleaned not in candidates:
            candidates.append(cleaned)

    last_error: Exception | None = None
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            continue

    snippet = raw[:300].replace("\n", " ")
    raise ValueError(f"Failed to parse LLM JSON output. Snippet: {snippet}") from last_error


def parse_structured_response(response: object) -> dict:
    """Parse a GenAI structured response with safe fallbacks."""
    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, dict):
        return parsed

    text = getattr(response, "text", None)
    if isinstance(text, str) and text.strip():
        return robust_json_loads(text)

    raise ValueError("Model response did not include structured JSON output.")
