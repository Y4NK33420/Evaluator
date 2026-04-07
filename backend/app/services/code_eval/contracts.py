"""Execution contracts for planned code-evaluator pipeline integration."""

from __future__ import annotations

from enum import Enum

try:
    from enum import StrEnum
except ImportError:  # Python < 3.11
    class StrEnum(str, Enum):
        pass

from pydantic import BaseModel, Field


class LanguageRuntime(StrEnum):
    PYTHON = "python"
    CPP = "cpp"
    C = "c"
    JAVA = "java"


class InputMode(StrEnum):
    STDIN = "stdin"
    ARGS = "args"
    FILE = "file"


class EnvironmentSpecMode(StrEnum):
    """Standardized instructor-facing environment specification formats."""

    MANIFEST = "manifest"
    LOCKFILE = "lockfile"
    IMAGE_REFERENCE = "image_reference"


class TestAuthoringMode(StrEnum):
    """How testcases are authored before grading."""

    INSTRUCTOR_PROVIDED_IO = "instructor_provided_io"
    QUESTION_AND_SOLUTION_TO_TESTS = "question_and_solution_to_tests"
    QUESTION_TO_SOLUTION_AND_TESTS = "question_to_solution_and_tests"


class EnvironmentReuseMode(StrEnum):
    """Environment reuse strategy across course/assignment boundaries."""

    COURSE_REUSE_WITH_ASSIGNMENT_OVERRIDES = "course_reuse_with_assignment_overrides"
    ASSIGNMENT_ONLY = "assignment_only"


class QualityEvaluationMode(StrEnum):
    """Code quality review modes."""

    DISABLED = "disabled"
    RUBRIC_ONLY = "rubric_only"
    RUBRIC_AND_HEURISTICS = "rubric_and_heuristics"


class QualityRubricSourceMode(StrEnum):
    """How the code-quality rubric is provided."""

    INSTRUCTOR_PROVIDED = "instructor_provided"
    AI_GENERATED_WITH_APPROVAL = "ai_generated_with_approval"


class RegradePolicy(StrEnum):
    """Policy for handling submissions after rubric/test/environment changes."""

    NEW_ONLY_UNLESS_EXPLICIT = "new_only_unless_explicit"
    FORCE_REPROCESS_ALL = "force_reprocess_all"


class ExecutionQuota(BaseModel):
    timeout_seconds: float = Field(default=5.0, gt=0, le=60)
    memory_mb: int = Field(default=256, ge=64, le=4096)
    max_output_kb: int = Field(default=256, ge=16, le=4096)
    network_enabled: bool = False


class EnvironmentSpec(BaseModel):
    """Normalized environment spec resolved into a reusable frozen snapshot."""

    mode: EnvironmentSpecMode = EnvironmentSpecMode.MANIFEST
    reuse_mode: EnvironmentReuseMode = (
        EnvironmentReuseMode.COURSE_REUSE_WITH_ASSIGNMENT_OVERRIDES
    )
    course_profile_key: str | None = None
    runtime: str = "python-3.11"
    freeze_key: str | None = None
    manifest: dict[str, str] = Field(default_factory=dict)
    assignment_overrides: dict[str, str] = Field(default_factory=dict)
    lockfile_content: str | None = None
    image_reference: str | None = None
    snapshot_vmstate_path: str | None = None
    snapshot_mem_path: str | None = None
    snapshot_vmstate_sha256: str | None = None
    snapshot_mem_sha256: str | None = None
    clean_strategy: str = "ephemeral_clone"


class TestAuthoringPlan(BaseModel):
    """Captures testcase-generation source and approval workflow."""

    mode: TestAuthoringMode = TestAuthoringMode.INSTRUCTOR_PROVIDED_IO
    question_text: str | None = None
    instructor_solution: str | None = None
    ai_generated_solution: str | None = None
    generation_script: str | None = None
    require_separate_approvals: bool = True
    solution_approved_by: str | None = None
    tests_approved_by: str | None = None
    approval_required: bool = True


class QualityEvaluationConfig(BaseModel):
    """Config for Gemini-based quality scoring in addition to correctness."""

    mandatory_per_assignment: bool = True
    mode: QualityEvaluationMode = QualityEvaluationMode.DISABLED
    rubric_source_mode: QualityRubricSourceMode = QualityRubricSourceMode.INSTRUCTOR_PROVIDED
    weight_percent: float = Field(default=0.0, ge=0.0, le=100.0)
    rubric: str | None = None
    dimensions: list[str] = Field(
        default_factory=lambda: [
            "correctness_style",
            "readability",
            "structure",
            "naming",
            "error_handling",
            "documentation",
        ]
    )
    rubric_approved_by: str | None = None
    model_name: str | None = None


class TestCaseSpec(BaseModel):
    testcase_id: str
    weight: float = Field(default=1.0, gt=0)
    input_mode: InputMode = InputMode.STDIN
    stdin: str | None = None
    argv: list[str] = Field(default_factory=list)
    files: dict[str, str] = Field(default_factory=dict)
    expected_stdout: str | None = None
    expected_stderr: str | None = None
    expected_exit_code: int = 0


class CodeEvalJobRequest(BaseModel):
    assignment_id: str
    submission_id: str
    language: LanguageRuntime
    entrypoint: str
    source_files: dict[str, str]
    testcases: list[TestCaseSpec]
    environment: EnvironmentSpec = Field(default_factory=EnvironmentSpec)
    test_authoring: TestAuthoringPlan | None = None
    quality_evaluation: QualityEvaluationConfig = Field(default_factory=QualityEvaluationConfig)
    regrade_policy: RegradePolicy = RegradePolicy.NEW_ONLY_UNLESS_EXPLICIT
    quota: ExecutionQuota = Field(default_factory=ExecutionQuota)


class AttemptResult(BaseModel):
    stage: str
    passed: bool
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    score: float = 0.0
    shim_used: bool = False
    shim_source: str | None = None


class CodeEvalJobResult(BaseModel):
    job_id: str
    submission_id: str
    total_score: float
    max_score: float
    status: str
    attempts: list[AttemptResult] = Field(default_factory=list)
