"""Shared google-genai client factory with stable Vertex env handling."""

from __future__ import annotations

import logging
import os
import random
import time

from google import genai
from google.genai import types

from app.config import get_settings
from app.services.json_utils import parse_structured_response

settings = get_settings()
log = logging.getLogger(__name__)

_DEFAULT_SAFETY_SETTINGS = [
    types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold="OFF"),
    types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="OFF"),
    types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="OFF"),
    types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="OFF"),
]


class ModelServiceError(RuntimeError):
    """Base class for user-facing model service failures."""


class ModelServiceTransientError(ModelServiceError):
    """Raised when model service fails transiently (retryable)."""


class ModelServicePermanentError(ModelServiceError):
    """Raised when model service fails with non-retryable errors."""

def _set_if_present(name: str, value: str | None) -> None:
    if value and value.strip():
        os.environ[name] = value.strip()


def _extract_status_code(exc: Exception) -> int | None:
    status_code = getattr(exc, "status_code", None)
    if isinstance(status_code, int):
        return status_code
    if isinstance(status_code, str) and status_code.isdigit():
        return int(status_code)
    return None


def is_transient_model_exception(exc: Exception) -> bool:
    status_code = _extract_status_code(exc)
    if status_code in {429, 500, 502, 503, 504}:
        return True

    text = str(exc).upper()
    transient_tokens = (
        "RESOURCE_EXHAUSTED",
        "RATE LIMIT",
        "TOO MANY REQUESTS",
        "TEMPORAR",
        "UNAVAILABLE",
        "TIMEOUT",
        "CONNECTION RESET",
        "TRY AGAIN LATER",
    )
    return any(token in text for token in transient_tokens)


def user_facing_model_error(operation: str, exc: Exception) -> str:
    status_code = _extract_status_code(exc)
    if is_transient_model_exception(exc):
        prefix = f"{operation} temporarily unavailable"
        if status_code:
            prefix += f" (HTTP {status_code})"
        return (
            f"{prefix}. The model service is currently overloaded or rate-limited. "
            "Please retry in a few minutes."
        )

    if status_code == 401:
        return (
            f"{operation} failed due to model authentication configuration (HTTP 401). "
            "Please verify API key/project settings."
        )

    if status_code in {403, 404}:
        return (
            f"{operation} failed because the configured model is unavailable for this project "
            f"(HTTP {status_code})."
        )

    if status_code == 400:
        return (
            f"{operation} request was rejected by model validation (HTTP 400). "
            "Please verify model configuration and request schema."
        )

    return f"{operation} failed: {exc}"


def _backoff_seconds(attempt: int) -> float:
    base = max(0.1, settings.model_retry_initial_backoff_seconds)
    cap = max(base, settings.model_retry_max_backoff_seconds)
    exponential = min(cap, base * (2 ** max(0, attempt - 1)))
    jitter = random.uniform(0.0, min(1.0, exponential * 0.25))
    return exponential + jitter


def make_genai_client() -> genai.Client:
    # Keep env and SDK flags aligned so Vertex API-key mode resolves correctly.
    _set_if_present("GOOGLE_CLOUD_PROJECT", settings.google_cloud_project)
    _set_if_present("GOOGLE_CLOUD_LOCATION", settings.google_cloud_location)
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = (
        "true" if settings.google_genai_use_vertexai else "false"
    )

    kwargs: dict[str, object] = {
        "vertexai": settings.google_genai_use_vertexai,
    }
    if settings.google_cloud_api_key and settings.google_cloud_api_key.strip():
        kwargs["api_key"] = settings.google_cloud_api_key.strip()

    return genai.Client(**kwargs)


def build_structured_json_config(
    *,
    response_schema: dict,
    system_instruction: str | None = None,
    temperature: float = 0.0,
    top_p: float = 0.95,
    max_output_tokens: int = 8192,
    thinking_level: str | None = None,
) -> types.GenerateContentConfig:
    """Create a consistent structured-output config for Gemini SDK calls."""
    kwargs: dict[str, object] = {
        "temperature": temperature,
        "top_p": top_p,
        "max_output_tokens": max_output_tokens,
        "safety_settings": _DEFAULT_SAFETY_SETTINGS,
        "response_mime_type": "application/json",
        "response_schema": response_schema,
    }
    if thinking_level:
        kwargs["thinking_config"] = types.ThinkingConfig(thinking_level=thinking_level)
    if system_instruction:
        kwargs["system_instruction"] = system_instruction
    return types.GenerateContentConfig(**kwargs)


def generate_structured_json_with_retry(
    *,
    model_name: str,
    contents: object,
    config: types.GenerateContentConfig,
    operation: str,
) -> dict:
    """Call Gemini SDK with explicit transient retry/backoff and structured parsing."""
    max_attempts = max(1, settings.model_transient_max_retries)
    client = make_genai_client()

    for attempt in range(1, max_attempts + 1):
        try:
            resp = client.models.generate_content(
                model=model_name,
                contents=contents,
                config=config,
            )
            return parse_structured_response(resp)
        except Exception as exc:
            transient = is_transient_model_exception(exc)
            if transient and attempt < max_attempts:
                delay = _backoff_seconds(attempt)
                log.warning(
                    "%s transient model error on attempt %d/%d: %s. Retrying in %.2fs",
                    operation,
                    attempt,
                    max_attempts,
                    exc,
                    delay,
                )
                time.sleep(delay)
                continue

            message = user_facing_model_error(operation, exc)
            if transient:
                raise ModelServiceTransientError(message) from exc
            raise ModelServicePermanentError(message) from exc

    raise ModelServiceTransientError(
        f"{operation} temporarily unavailable after retry attempts."
    )
