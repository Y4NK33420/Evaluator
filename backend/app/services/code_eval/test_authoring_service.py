"""AI-assisted test case authoring for code-eval assignments.

Implements TestAuthoringMode 2 and 3:
  - Mode 2 (QUESTION_AND_SOLUTION_TO_TESTS): Given question text + instructor solution,
    generate TestCaseSpec drafts.
  - Mode 3 (QUESTION_TO_SOLUTION_AND_TESTS): Given question text only, generate
    a solution + test cases (both require separate approval before use).

Coverage gate (enforced at generation AND approval time):
  - At least 2 happy_path test cases
  - At least 1 edge_case test case
  - No testcase may have empty expected_stdout AND expected_exit_code=0

Gemini response schema is strict — unknown or malformed responses are rejected
with an explicit error rather than silently accepted.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from app.config import get_settings
from app.services.code_eval.contracts import (
    InputMode,
    LanguageRuntime,
    TestAuthoringMode,
    TestCaseSpec,
)
from app.services.genai_client import (
    ModelServiceError,
    build_structured_json_config,
    generate_structured_json_with_retry,
)

log = logging.getLogger(__name__)
settings = get_settings()

_VALID_TESTCASE_CLASSES = {"happy_path", "edge_case", "invalid_input", "performance", "boundary"}
_VALID_INPUT_MODES = {"stdin", "args", "file"}

_COVERAGE_MIN_HAPPY_PATH = 2
_COVERAGE_MIN_EDGE_CASE = 1


# ── Gemini schema ─────────────────────────────────────────────────────────────

_TESTCASE_SCHEMA = {
    "type": "OBJECT",
    "required": ["testcase_id", "testcase_class", "input_mode", "expected_exit_code", "weight"],
    "properties": {
        "testcase_id": {"type": "STRING"},
        "testcase_class": {
            "type": "STRING",
            "enum": list(_VALID_TESTCASE_CLASSES),
        },
        "description": {"type": "STRING"},
        "input_mode": {
            "type": "STRING",
            "enum": list(_VALID_INPUT_MODES),
        },
        "stdin": {"type": "STRING"},
        "argv": {
            "type": "ARRAY",
            "items": {"type": "STRING"},
        },
        "expected_stdout": {"type": "STRING"},
        "expected_stderr": {"type": "STRING"},
        "expected_exit_code": {"type": "INTEGER"},
        "weight": {"type": "NUMBER"},
    },
}

_RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "required": ["testcases", "coverage_notes"],
    "properties": {
        "testcases": {
            "type": "ARRAY",
            "items": _TESTCASE_SCHEMA,
        },
        "entrypoint": {"type": "STRING"},
        "coverage_notes": {"type": "STRING"},
        "class_distribution": {
            "type": "OBJECT",
            "additionalProperties": {"type": "INTEGER"},
        },
        # Only present in Mode 3
        "generated_solution": {"type": "STRING"},
    },
}

_SOLUTION_AND_TESTS_SCHEMA = {
    "type": "OBJECT",
    "required": ["generated_solution", "testcases", "coverage_notes"],
    "properties": {
        "generated_solution": {"type": "STRING"},
        "solution_entrypoint": {"type": "STRING"},
        "testcases": {
            "type": "ARRAY",
            "items": _TESTCASE_SCHEMA,
        },
        "coverage_notes": {"type": "STRING"},
        "class_distribution": {
            "type": "OBJECT",
            "additionalProperties": {"type": "INTEGER"},
        },
    },
}


# ── Coverage validation ───────────────────────────────────────────────────────

class CoverageError(ValueError):
    """Raised when generated test cases don't meet minimum coverage requirements."""
    pass


def _validate_coverage(testcases: list[dict[str, Any]]) -> None:
    """Enforce minimum testcase class coverage. Raises CoverageError if violated."""
    class_counts: dict[str, int] = {}
    for tc in testcases:
        cls = str(tc.get("testcase_class") or "unknown")
        class_counts[cls] = class_counts.get(cls, 0) + 1

    happy_count = class_counts.get("happy_path", 0)
    edge_count = class_counts.get("edge_case", 0)

    errors: list[str] = []
    if happy_count < _COVERAGE_MIN_HAPPY_PATH:
        errors.append(
            f"happy_path coverage insufficient: got {happy_count}, need >= {_COVERAGE_MIN_HAPPY_PATH}"
        )
    if edge_count < _COVERAGE_MIN_EDGE_CASE:
        errors.append(
            f"edge_case coverage insufficient: got {edge_count}, need >= {_COVERAGE_MIN_EDGE_CASE}"
        )

    # Check for empty expected output on passing cases
    for tc in testcases:
        if tc.get("expected_exit_code", 0) == 0:
            stdout = tc.get("expected_stdout")
            if stdout is None or str(stdout).strip() == "":
                errors.append(
                    f"testcase '{tc.get('testcase_id')}' has expected_exit_code=0 but "
                    f"empty/null expected_stdout — this would pass any output"
                )

    if errors:
        raise CoverageError(
            "Generated test cases failed coverage gate: " + "; ".join(errors)
        )


def _parse_testcase_spec(raw: dict[str, Any], idx: int) -> TestCaseSpec:
    """Parse and validate a single testcase dict from AI response."""
    tc_id = str(raw.get("testcase_id") or f"tc_{idx + 1:03d}")
    input_mode_raw = str(raw.get("input_mode") or "stdin").lower()
    if input_mode_raw not in _VALID_INPUT_MODES:
        raise ValueError(
            f"testcase[{idx}].input_mode='{input_mode_raw}' is invalid. "
            f"Must be one of: {sorted(_VALID_INPUT_MODES)}"
        )

    weight_raw = raw.get("weight", 1.0)
    try:
        weight = float(weight_raw)
    except (TypeError, ValueError):
        raise ValueError(f"testcase[{idx}].weight must be a number, got {weight_raw!r}")
    if weight <= 0:
        raise ValueError(f"testcase[{idx}].weight must be > 0, got {weight}")

    argv_raw = raw.get("argv")
    argv: list[str] = []
    if isinstance(argv_raw, list):
        argv = [str(a) for a in argv_raw]

    return TestCaseSpec(
        testcase_id=tc_id,
        weight=weight,
        input_mode=InputMode(input_mode_raw),
        stdin=str(raw["stdin"]) if raw.get("stdin") is not None else None,
        argv=argv,
        files={},
        expected_stdout=str(raw["expected_stdout"]) if raw.get("expected_stdout") is not None else None,
        expected_stderr=str(raw["expected_stderr"]) if raw.get("expected_stderr") is not None else None,
        expected_exit_code=int(raw.get("expected_exit_code", 0)),
    )


def _parse_testcase_list(raw_list: list[Any]) -> list[TestCaseSpec]:
    """Parse and validate a list of raw testcase dicts."""
    if not isinstance(raw_list, list) or not raw_list:
        raise ValueError("AI response contained no testcases")

    specs: list[TestCaseSpec] = []
    seen_ids: set[str] = set()
    for idx, raw in enumerate(raw_list):
        if not isinstance(raw, dict):
            raise ValueError(f"testcase[{idx}] is not a dict, got {type(raw).__name__}")
        spec = _parse_testcase_spec(raw, idx)
        if spec.testcase_id in seen_ids:
            spec = spec.model_copy(update={"testcase_id": f"{spec.testcase_id}_{idx}"})
        seen_ids.add(spec.testcase_id)
        specs.append(spec)
    return specs


# ── System instructions ───────────────────────────────────────────────────────

_SYSTEM_INSTRUCTION = (
    "You are an expert programming instructor designing test cases for automated grading. "
    "Generate test cases that are pedagogically sound, cover common mistakes, and have "
    "deterministic expected outputs. "
    "Each testcase_class must be one of: happy_path, edge_case, invalid_input, performance, boundary. "
    "The expected_stdout must be the EXACT output the correct program would produce, "
    "including trailing newlines if applicable. "
    "Do NOT include test cases whose expected output is ambiguous or runtime-dependent. "
    "Weight happy_path cases at 1.0, edge_case/boundary at 1.5, invalid_input at 0.5."
)


# ── Public API ─────────────────────────────────────────────────────────────────

def generate_testcases_from_question_and_solution(
    *,
    question_text: str,
    solution_code: str,
    language: str,
    entrypoint: str,
    num_cases: int = 6,
    include_classes: list[str] | None = None,
) -> dict[str, Any]:
    """Mode 2: Generate TestCaseSpec[] from question text + instructor/AI solution.

    Args:
        question_text: The assignment question as plain text.
        solution_code: Working solution code (instructor-provided or pre-approved AI).
        language: One of python, c, cpp, java.
        entrypoint: The expected entrypoint filename.
        num_cases: Target number of test cases to generate (default 6).
        include_classes: Testcase classes to include. If None, uses all.

    Returns:
        dict with keys: testcases (list[TestCaseSpec]), coverage_notes, class_distribution,
        entrypoint, generation_metadata.

    Raises:
        ModelServiceError: If Gemini call fails after retries.
        ValueError: If response fails schema or coverage validation.
        CoverageError: If generated cases don't meet minimum coverage.
    """
    classes_to_use = include_classes or list(_VALID_TESTCASE_CLASSES)
    model_name = settings.resolve_code_healing_model()

    prompt_payload = {
        "task": "Generate test cases for automated code evaluation",
        "mode": TestAuthoringMode.QUESTION_AND_SOLUTION_TO_TESTS.value,
        "language": language,
        "entrypoint": entrypoint,
        "target_count": num_cases,
        "required_classes": classes_to_use,
        "question": question_text,
        "solution_code": solution_code[:8000],  # truncate for prompt safety
        "constraints": [
            "All expected_stdout values must be exact byte-for-byte output of the solution",
            "Use stdin input_mode unless the assignment clearly uses argv or files",
            "Do not generate test cases that require network or filesystem access beyond /tmp",
            f"Generate at least {_COVERAGE_MIN_HAPPY_PATH} happy_path and {_COVERAGE_MIN_EDGE_CASE} edge_case cases",
        ],
    }

    config = build_structured_json_config(
        response_schema=_RESPONSE_SCHEMA,
        system_instruction=_SYSTEM_INSTRUCTION,
        temperature=0.1,
        max_output_tokens=8192,
    )

    log.info(
        "test_authoring: generating %d testcases for lang=%s entrypoint=%s via model=%s",
        num_cases, language, entrypoint, model_name,
    )

    try:
        model_output = generate_structured_json_with_retry(
            model_name=model_name,
            contents=[{"role": "user", "parts": [{"text": str(prompt_payload)}]}],
            config=config,
            operation="AI test case generation (mode 2)",
        )
    except ModelServiceError as exc:
        log.error("test_authoring: model error for lang=%s: %s", language, exc)
        raise

    raw_testcases = model_output.get("testcases") or []
    testcase_specs = _parse_testcase_list(raw_testcases)

    # Coverage gate
    raw_for_coverage = [tc.model_dump(mode="json") for tc in testcase_specs]
    # Attach testcase_class from raw for coverage check (it's not in TestCaseSpec)
    for i, raw in enumerate(raw_testcases):
        if i < len(raw_for_coverage):
            raw_for_coverage[i]["testcase_class"] = raw.get("testcase_class", "happy_path")
    _validate_coverage(raw_for_coverage)

    coverage_notes = str(model_output.get("coverage_notes") or "")
    class_distribution = model_output.get("class_distribution") or {}

    log.info(
        "test_authoring: generated %d testcases coverage=%s",
        len(testcase_specs), class_distribution,
    )

    return {
        "testcases": [tc.model_dump(mode="json") for tc in testcase_specs],
        "testcase_raw_with_classes": [
            {**raw_testcases[i], "parsed_id": testcase_specs[i].testcase_id}
            for i in range(len(testcase_specs))
        ],
        "entrypoint": str(model_output.get("entrypoint") or entrypoint),
        "coverage_notes": coverage_notes,
        "class_distribution": class_distribution,
        "generation_metadata": {
            "mode": TestAuthoringMode.QUESTION_AND_SOLUTION_TO_TESTS.value,
            "model": model_name,
            "language": language,
            "num_requested": num_cases,
            "num_generated": len(testcase_specs),
        },
    }


def generate_solution_and_testcases_from_question(
    *,
    question_text: str,
    language: str,
    entrypoint: str,
    num_cases: int = 6,
) -> dict[str, Any]:
    """Mode 3: Generate a solution + TestCaseSpec[] from question text alone.

    Both the solution and test cases require separate instructor approvals
    before they can be used for grading (enforced at the API layer).

    Returns:
        dict with keys: generated_solution, testcases, coverage_notes,
        class_distribution, entrypoint, generation_metadata.

    Raises:
        ModelServiceError: If Gemini call fails.
        ValueError / CoverageError: On validation failure.
    """
    model_name = settings.resolve_code_healing_model()

    prompt_payload = {
        "task": "Generate a correct solution and test cases for automated code evaluation",
        "mode": TestAuthoringMode.QUESTION_TO_SOLUTION_AND_TESTS.value,
        "language": language,
        "entrypoint": entrypoint,
        "target_count": num_cases,
        "question": question_text,
        "constraints": [
            f"Write a correct {language} solution that solves the problem completely",
            "Generate test cases whose expected_stdout is computed from the solution",
            f"Generate at least {_COVERAGE_MIN_HAPPY_PATH} happy_path and {_COVERAGE_MIN_EDGE_CASE} edge_case cases",
            "The solution must be self-contained (no external deps unless specified)",
        ],
    }

    config = build_structured_json_config(
        response_schema=_SOLUTION_AND_TESTS_SCHEMA,
        system_instruction=_SYSTEM_INSTRUCTION,
        temperature=0.1,
        max_output_tokens=16384,
    )

    log.info(
        "test_authoring: generating solution+testcases for lang=%s entrypoint=%s via model=%s",
        language, entrypoint, model_name,
    )

    try:
        model_output = generate_structured_json_with_retry(
            model_name=model_name,
            contents=[{"role": "user", "parts": [{"text": str(prompt_payload)}]}],
            config=config,
            operation="AI solution+test generation (mode 3)",
        )
    except ModelServiceError as exc:
        log.error("test_authoring: mode3 model error for lang=%s: %s", language, exc)
        raise

    generated_solution = str(model_output.get("generated_solution") or "")
    if not generated_solution.strip():
        raise ValueError("AI response contained an empty generated_solution")

    raw_testcases = model_output.get("testcases") or []
    testcase_specs = _parse_testcase_list(raw_testcases)

    raw_for_coverage = [tc.model_dump(mode="json") for tc in testcase_specs]
    for i, raw in enumerate(raw_testcases):
        if i < len(raw_for_coverage):
            raw_for_coverage[i]["testcase_class"] = raw.get("testcase_class", "happy_path")
    _validate_coverage(raw_for_coverage)

    coverage_notes = str(model_output.get("coverage_notes") or "")
    class_distribution = model_output.get("class_distribution") or {}
    solution_entrypoint = str(model_output.get("solution_entrypoint") or entrypoint)

    log.info(
        "test_authoring: mode3 generated solution+%d testcases coverage=%s",
        len(testcase_specs), class_distribution,
    )

    return {
        "generated_solution": generated_solution,
        "solution_entrypoint": solution_entrypoint,
        "testcases": [tc.model_dump(mode="json") for tc in testcase_specs],
        "testcase_raw_with_classes": [
            {**raw_testcases[i], "parsed_id": testcase_specs[i].testcase_id}
            for i in range(len(testcase_specs))
        ],
        "entrypoint": solution_entrypoint,
        "coverage_notes": coverage_notes,
        "class_distribution": class_distribution,
        "generation_metadata": {
            "mode": TestAuthoringMode.QUESTION_TO_SOLUTION_AND_TESTS.value,
            "model": model_name,
            "language": language,
            "num_requested": num_cases,
            "num_generated": len(testcase_specs),
            "requires_dual_approval": True,
        },
    }


def validate_testcase_draft_coverage(testcases_raw: list[dict[str, Any]]) -> None:
    """Re-validate coverage at approval time (called from the approve endpoint).

    Raises:
        CoverageError: If the draft doesn't meet minimum coverage requirements.
    """
    _validate_coverage(testcases_raw)


def draft_to_testcase_specs(testcases_raw: list[dict[str, Any]]) -> list[TestCaseSpec]:
    """Convert a persisted draft (from content_json) to canonical TestCaseSpec list.

    Called at approval time to convert the AI draft into the spec format used by jobs.
    """
    return _parse_testcase_list(testcases_raw)
