"""Language profile presets for code-eval runtime selection."""

from __future__ import annotations

from typing import Any

_LANGUAGE_PROFILES: dict[str, dict[str, Any]] = {
    "python": {
        "runtime": "python-3.11",
        "source_extension": ".py",
        "docker_image": "python:3.11-slim",
        "compile_required": False,
    },
    "c": {
        "runtime": "c-gcc-13",
        "source_extension": ".c",
        "docker_image": "gcc:13",
        "compile_required": True,
    },
    "cpp": {
        "runtime": "cpp-gpp-13",
        "source_extension": ".cpp",
        "docker_image": "gcc:13",
        "compile_required": True,
    },
    "java": {
        "runtime": "java-21",
        "source_extension": ".java",
        "docker_image": "eclipse-temurin:21",
        "compile_required": True,
    },
}


def get_language_profile(language: str) -> dict[str, Any]:
    key = str(language).strip().lower()
    if key not in _LANGUAGE_PROFILES:
        raise ValueError(f"Unsupported language runtime: {language}")
    return dict(_LANGUAGE_PROFILES[key])
