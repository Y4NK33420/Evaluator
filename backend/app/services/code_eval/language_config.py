"""Standardized per-language execution configuration with library/flag support.

Instructors author a language_config block inside spec_json when creating an
environment version. This module parses and validates that block, merging it
with per-language defaults from language_profiles.py.

Schema (as dict inside spec_json["language_config"]):
  {
    "language": "python",            # required — must match job.language
    "packages": ["numpy==2.0.0"],    # pip packages (python) / apt packages (c/cpp)
    "compile_flags": ["-Wall"],      # override profile defaults
    "link_flags": ["-lm"],           # C/C++ linker flags
    "run_flags": ["-Xmx256m"],       # JVM / interpreter flags
    "classpath_jars": ["lib/x.jar"], # Java only — relative paths
    "entrypoint_style": "module"     # module | class | binary (informational)
  }

Unknown keys raise ValueError (no silent ignoring).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.services.code_eval.language_profiles import get_language_profile

_KNOWN_KEYS = {
    "language",
    "packages",
    "compile_flags",
    "link_flags",
    "run_flags",
    "classpath_jars",
    "entrypoint_style",
}

_VALID_ENTRYPOINT_STYLES = {"module", "class", "binary", "script"}


@dataclass
class LanguageConfig:
    """Resolved, merged language configuration for a code-eval job."""

    language: str
    packages: list[str] = field(default_factory=list)
    compile_flags: list[str] = field(default_factory=list)
    link_flags: list[str] = field(default_factory=list)
    run_flags: list[str] = field(default_factory=list)
    classpath_jars: list[str] = field(default_factory=list)
    entrypoint_style: str = "module"  # informational; used by UI and shim

    def full_compile_command(
        self, compiler: str, source_files: list[str], output_path: str
    ) -> list[str]:
        """Build full compile invocation for C/C++."""
        cmd = [compiler, *source_files]
        cmd.extend(self.compile_flags)
        cmd.extend(["-o", output_path])
        cmd.extend(self.link_flags)
        return cmd

    def full_java_compile_command(self, source_files: list[str]) -> list[str]:
        """Build full javac invocation."""
        cmd = ["javac"]
        cmd.extend(self.compile_flags)
        cmd.extend(source_files)
        return cmd

    def full_java_run_command(self, class_name: str) -> list[str]:
        """Build full java run invocation."""
        cp = ":".join([".", *self.classpath_jars]) if self.classpath_jars else "."
        cmd = ["java", *self.run_flags, "-cp", cp, class_name]
        return cmd


def _ensure_str_list(value: Any, key: str) -> list[str]:
    """Validate that a config value is a list of strings, raise explicitly if not."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(
            f"language_config.{key} must be a list, got {type(value).__name__}"
        )
    result = []
    for i, item in enumerate(value):
        if not isinstance(item, str):
            raise ValueError(
                f"language_config.{key}[{i}] must be a string, got {type(item).__name__}"
            )
        result.append(item)
    return result


def parse_language_config(
    spec_json: dict[str, Any] | None,
    *,
    job_language: str,
) -> LanguageConfig:
    """Parse and validate a language_config block from spec_json.

    Args:
        spec_json: The environment version's spec_json dict (may be None).
        job_language: The language declared in CodeEvalJobRequest.language.

    Returns:
        LanguageConfig with profile defaults merged with instructor overrides.

    Raises:
        ValueError: On unknown keys, type mismatches, or language mismatch.
    """
    spec = spec_json or {}
    raw = spec.get("language_config")

    # If instructor omitted language_config entirely, use profile defaults.
    if raw is None:
        return _from_profile_defaults(job_language)

    if not isinstance(raw, dict):
        raise ValueError(
            f"spec_json.language_config must be a dict, got {type(raw).__name__}"
        )

    # Reject unknown keys explicitly — no silent ignoring.
    unknown = set(raw.keys()) - _KNOWN_KEYS
    if unknown:
        raise ValueError(
            f"Unknown keys in language_config: {sorted(unknown)}. "
            f"Allowed keys: {sorted(_KNOWN_KEYS)}"
        )

    # Language declared in config must match the job.
    config_lang = raw.get("language")
    if config_lang is not None:
        if str(config_lang).strip().lower() != job_language.strip().lower():
            raise ValueError(
                f"language_config.language='{config_lang}' does not match "
                f"job language='{job_language}'"
            )

    profile = get_language_profile(job_language)

    # Merge: instructor overrides win; profile defaults fill gaps.
    compile_flags = _ensure_str_list(raw.get("compile_flags"), "compile_flags")
    if not compile_flags:
        compile_flags = list(profile.get("default_compile_flags", []))

    link_flags = _ensure_str_list(raw.get("link_flags"), "link_flags")
    if not link_flags:
        link_flags = list(profile.get("default_link_flags", []))

    run_flags = _ensure_str_list(raw.get("run_flags"), "run_flags")
    if not run_flags:
        run_flags = list(profile.get("default_run_flags", []))

    classpath_jars = _ensure_str_list(raw.get("classpath_jars"), "classpath_jars")
    packages = _ensure_str_list(raw.get("packages"), "packages")

    entrypoint_style_raw = raw.get("entrypoint_style", "module")
    if not isinstance(entrypoint_style_raw, str):
        raise ValueError("language_config.entrypoint_style must be a string")
    entrypoint_style = entrypoint_style_raw.strip().lower()
    if entrypoint_style not in _VALID_ENTRYPOINT_STYLES:
        raise ValueError(
            f"language_config.entrypoint_style='{entrypoint_style}' is invalid. "
            f"Must be one of: {sorted(_VALID_ENTRYPOINT_STYLES)}"
        )

    return LanguageConfig(
        language=job_language,
        packages=packages,
        compile_flags=compile_flags,
        link_flags=link_flags,
        run_flags=run_flags,
        classpath_jars=classpath_jars,
        entrypoint_style=entrypoint_style,
    )


def _from_profile_defaults(language: str) -> LanguageConfig:
    """Build LanguageConfig purely from profile defaults (no instructor spec)."""
    profile = get_language_profile(language)
    return LanguageConfig(
        language=language,
        packages=[],
        compile_flags=list(profile.get("default_compile_flags", [])),
        link_flags=list(profile.get("default_link_flags", [])),
        run_flags=list(profile.get("default_run_flags", [])),
        classpath_jars=[],
        entrypoint_style=profile.get("default_entrypoint_style", "module"),
    )
