"""Application settings — all overridable via environment variables or .env file."""

from functools import lru_cache
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # ── App ───────────────────────────────────────────────────────────────────
    app_name:    str  = "AMGS Backend"
    debug:       bool = False
    secret_key:  str  = "change-me-in-production"

    # ── Database ──────────────────────────────────────────────────────────────
    database_url: str = "postgresql+psycopg2://amgs:amgs@postgres:5432/amgs"

    # ── Redis / Celery ────────────────────────────────────────────────────────
    redis_url:    str = "redis://redis:6379/0"

    # ── OCR Service ───────────────────────────────────────────────────────────
    ocr_service_url: str = "http://ocr-service:8000"

    # ── Google models (env-driven, with default fallback) ────────────────
    google_cloud_api_key: str = ""
    google_genai_use_vertexai: bool = True
    google_cloud_project: str | None = None
    google_cloud_location: str | None = None
    default_model:               str | None = None
    subjective_ocr_model:        str | None = None
    objective_ocr_model:         str | None = None
    subjective_grading_model:    str | None = None
    objective_grading_model:     str | None = None
    rubrics_generation_model:    str | None = None
    code_healing_model:          str | None = None

    # ── Model transient retry handling ───────────────────────────────────────
    model_transient_max_retries: int = 3
    model_retry_initial_backoff_seconds: float = 1.5
    model_retry_max_backoff_seconds: float = 12.0

    # ── Google Classroom OAuth ────────────────────────────────────────────────
    google_credentials_file: str = "app/services/google_auth/credentials.json"
    google_token_file:       str = "app/services/google_auth/token.json"
    # Default course to use when not specified per-request
    google_classroom_default_course_id: str = ""

    # ── File storage ──────────────────────────────────────────────────────────
    uploads_dir: str = "/data/uploads"

    # ── OCR thresholds ────────────────────────────────────────────────────────
    ocr_confidence_threshold: float = 0.85

    # ── Code-eval execution backend ───────────────────────────────────────────
    code_eval_enable_local_execution: bool = False
    code_eval_execution_backend: str = "local"
    code_eval_docker_default_image: str = "python:3.11-slim"
    code_eval_docker_force_no_network: bool = True
    code_eval_docker_auto_pull: bool = True
    code_eval_enable_shim_retry: bool = True
    code_eval_enable_ai_shim_generation: bool = False
    code_eval_microvm_enable_adapter: bool = False
    code_eval_microvm_runtime_mode: str = "pending"
    code_eval_microvm_allow_fallback: bool = True
    code_eval_microvm_fallback_backend: str = "docker"
    code_eval_microvm_force_no_network: bool = True
    code_eval_microvm_serial_lock_file: str = "/tmp/codeeval-firecracker/firecracker-vsock.lock"
    code_eval_microvm_runtime_bridge_url: str = ""
    code_eval_microvm_runtime_bridge_api_key: str = ""
    code_eval_microvm_runtime_bridge_timeout_seconds: float = 30.0
    code_eval_microvm_runtime_bridge_verify_tls: bool = True
    code_eval_microvm_firecracker_bin: str = "/usr/local/bin/firecracker"
    code_eval_microvm_snapshot_vmstate_path: str = ""
    code_eval_microvm_snapshot_mem_path: str = ""
    code_eval_microvm_api_socket_dir: str = "/tmp/codeeval-firecracker/sockets"
    code_eval_microvm_runtime_workdir: str = "/tmp/codeeval-firecracker/runs"
    code_eval_microvm_firecracker_api_timeout_seconds: float = 5.0
    code_eval_microvm_vsock_guest_cid: int = 3
    code_eval_microvm_vsock_port: int = 7000
    code_eval_microvm_vsock_uds_path: str = "/tmp/firecracker-snap-python311.vsock"
    code_eval_microvm_vsock_connect_timeout_seconds: float = 5.0
    code_eval_microvm_env_build_strategy: str = "deterministic_key"
    code_eval_microvm_env_build_script: str = "/app/microvm/scripts/create_snapshot_with_guest_agent.sh"
    code_eval_microvm_env_build_snapshot_dir: str = "/opt/microvm/snapshots"
    code_eval_microvm_env_build_snapshot_name_prefix: str = "codeeval"

    @model_validator(mode="after")
    def _validate_default_model(self):
        if not (self.default_model and self.default_model.strip()):
            raise ValueError(
                "DEFAULT_MODEL is required. Set it in environment (.env or deployment env)."
            )
        return self

    def _resolve_model(self, specific_model: str | None) -> str:
        if specific_model and specific_model.strip():
            return specific_model.strip()
        # Safe because _validate_default_model enforces this.
        return self.default_model.strip()  # type: ignore[union-attr]

    def ocr_model_for(self, question_type: str) -> str:
        # Mixed assignments follow the subjective OCR path by design.
        if question_type == "objective":
            return self._resolve_model(self.objective_ocr_model)
        return self._resolve_model(self.subjective_ocr_model)

    def grading_model_for(self, question_type: str) -> str:
        # Mixed assignments follow the subjective grading path by design.
        if question_type == "objective":
            return self._resolve_model(self.objective_grading_model)
        return self._resolve_model(self.subjective_grading_model)

    def resolve_rubrics_generation_model(self) -> str:
        return self._resolve_model(self.rubrics_generation_model)

    def resolve_code_healing_model(self) -> str:
        return self._resolve_model(self.code_healing_model)


@lru_cache
def get_settings() -> Settings:
    return Settings()
