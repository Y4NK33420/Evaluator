"""Language profile presets for code-eval runtime selection.

Each profile defines:
  - docker_image: default container image to use for this language
  - compile_required: whether a compile step is needed before execution
  - default_compile_flags: flags passed to the compiler by default
  - default_link_flags: linker flags (C/C++ only)
  - default_run_flags: flags passed at runtime (JVM flags, interpreter flags)
  - default_entrypoint_style: how the entrypoint is interpreted

These are merged with instructor-authored language_config blocks by
language_config.py. Instructor overrides always win.
"""

from __future__ import annotations

from typing import Any

_LANGUAGE_PROFILES: dict[str, dict[str, Any]] = {
    "python": {
        "runtime": "python-3.11",
        "source_extension": ".py",
        "docker_image": "python:3.11-slim",
        "compile_required": False,
        "default_compile_flags": [],
        "default_link_flags": [],
        "default_run_flags": [],
        "default_entrypoint_style": "module",
    },
    "c": {
        "runtime": "c-gcc-13",
        "source_extension": ".c",
        "docker_image": "gcc:13",
        "compile_required": True,
        # -Wall -Wextra: catch common mistakes; -O2: sane perf; -std=c17; -lm always safe
        "default_compile_flags": ["-Wall", "-Wextra", "-O2", "-std=c17"],
        "default_link_flags": ["-lm"],
        "default_run_flags": [],
        "default_entrypoint_style": "binary",
    },
    "cpp": {
        "runtime": "cpp-gpp-13",
        "source_extension": ".cpp",
        "docker_image": "gcc:13",
        "compile_required": True,
        "default_compile_flags": ["-Wall", "-Wextra", "-O2", "-std=c++20", "-DNDEBUG"],
        "default_link_flags": ["-lm"],
        "default_run_flags": [],
        "default_entrypoint_style": "binary",
    },
    "java": {
        "runtime": "java-21",
        "source_extension": ".java",
        "docker_image": "eclipse-temurin:21",
        "compile_required": True,
        "default_compile_flags": ["-encoding", "UTF-8"],
        "default_link_flags": [],          # not applicable for Java
        "default_run_flags": ["-Xmx256m", "-Xss512k"],
        "default_entrypoint_style": "class",
    },
}


def get_language_profile(language: str) -> dict[str, Any]:
    """Return the profile for a language, raising explicitly if unsupported.

    Raises:
        ValueError: If the language is not in the profile registry.
    """
    key = str(language).strip().lower()
    if key not in _LANGUAGE_PROFILES:
        raise ValueError(
            f"Unsupported language runtime: '{language}'. "
            f"Supported: {sorted(_LANGUAGE_PROFILES.keys())}"
        )
    return dict(_LANGUAGE_PROFILES[key])


def is_compile_required(language: str) -> bool:
    """Return True if this language requires a compile step before execution."""
    return bool(get_language_profile(language).get("compile_required", False))


def get_docker_image(language: str) -> str:
    """Return the default docker image for a language."""
    return str(get_language_profile(language)["docker_image"])
