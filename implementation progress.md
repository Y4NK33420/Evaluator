# Implementation Progress

Date: 2026-04-07

This document consolidates implementation progress across the full workstream so far (not only the most recent debugging cycles). It is based on the PRD, the plan iteration history, and all code and runtime validation work completed in this repository.

## 0) Session Changelog (Newest First)

Practice:
- For every meaningful implementation session, add a dated summary entry here first.
- Keep each entry concise (what changed, what was validated, what remains).
- Link to raw validation artifacts in `logs/` whenever available.

### 2026-04-07

- Implemented environment build/freeze orchestration hooks for code-eval environment versions.
- Added API endpoints for build enqueue and publish-readiness validation.
- Added environment build Celery task (`code_eval_env_tasks`) with persisted build logs and deterministic freeze-key generation.
- Enforced environment readiness gate for job creation (`status=ready` and `freeze_key` required).
- Validated end-to-end flow: draft env -> build enqueue -> ready publish validation -> successful job execution.
- Integrated assignment publish workflow gates to require approved rubric and ready/frozen bound environment for code assignments.
- Validated publish lifecycle: blocked before env readiness, successful after build, republish requires explicit force.
- Implemented `AI_ANALYZING -> RETRYING_SHIM` execution path with deterministic, audit-friendly shim retry policy.
- Added strict shim gating so retries run only for whitespace-only interface mismatches; non-shimmable failures do not retry.
- Validated both paths: recoverable whitespace mismatch completes after retry, logical mismatch remains failed without retry.
- Added microVM execution adapter boundary behind backend selector (`CODE_EVAL_EXECUTION_BACKEND=microvm`).
- Implemented configurable microVM fallback policy to `local` or `docker` when adapter runtime integration is unavailable.
- Validated microVM modes: fallback-enabled jobs complete via fallback backend with adapter audit metadata, fallback-disabled jobs fail deterministically.
- Added explicit microVM runtime modes (`pending`, `pilot_local`, `pilot_docker`) under adapter control.
- Validated adapter-ready `pilot_local` mode (microvm path executes with `executor=microvm_adapter`, no fallback) and invalid-mode deterministic failure guard.
- Added pilot-mode environment policy gate at job creation for microVM runtime (`microvm_policy.allow_pilot_runtime` + `approved_by`).
- Validated `pilot_docker` path: approved policy environments run successfully; missing policy is blocked with `422` before enqueue.
- Fixed compose runtime parity issue by adding missing CODE_EVAL_* env vars to backend service so API and worker evaluate the same execution mode.
- Added microVM `runtime_bridge` mode to execute through an external HTTP runtime contract behind the same adapter boundary.
- Added runtime observability endpoint (`GET /code-eval/runtime/status`) exposing active backend/microvm mode and bridge readiness flags.
- Added pilot_docker image-reference preflight guard to fail early at job creation when no explicit image reference is provided.
- Validated runtime_bridge success path (mock bridge execution), runtime_bridge graceful fallback path (bridge not configured), and publish-time pilot policy checks.
- Added optional in-repo runtime bridge reference service (`runtime_bridge_service`) and wired it into compose as `runtime-bridge`.
- Validated compose-hosted runtime_bridge success path and deterministic auth-mismatch failure path (HTTP 401 surfaced in job failure metadata).
- Added automated compose smoke script for runtime_bridge success + auth-mismatch checks and default-restore verification.
- Extended runtime_bridge service internals with executor modes (`local_reference`, `microvm_transport`) behind the same `/execute` contract and validated end-to-end forwarding path.
- Added `firecracker_vsock` runtime mode with Firecracker snapshot restore + vsock guest-agent execution path in microVM adapter runtime.
- Added reference guest-agent implementation (`microvm_guest_agent/agent.py`) and validated deterministic prerequisite failure semantics on current host (missing Firecracker binary).
- Added explicit runtime preflight endpoint (`GET /code-eval/runtime/preflight`) and runtime-status preflight flags for firecracker mode (`firecracker_preflight_ready`, `firecracker_preflight_issues`).
- Added Linux/KVM deployment path for real Firecracker runs:
  - `backend/Dockerfile.microvm`
  - `docker-compose.microvm.yml`
  - `microvm/README.md`
  - scripted host preflight check (`logs/code_eval_firecracker_preflight.ps1`)

### 2026-04-06

- Added code-eval execution backend selector (`local` and `docker`) and validated both backend paths with live pass/fail jobs.
- Implemented docker backend via Docker SDK and fixed staging using archive upload (removed bind-mount path mismatch risk).
- Enforced code-eval policy gates at API level (mandatory quality config, approval prerequisites, testcase-class gate for AI tests).
- Reconciled Alembic state for pre-existing local schema using one-time `alembic stamp 002`.
- Updated documentation and saved raw runtime evidence under `logs/` for local and docker backend validations.

## 1) Scope Snapshot

Primary system goals implemented so far:
- OCR + grading pipeline for assignment submissions.
- Rubric-based grading with approval controls.
- Dockerized local stack for backend, workers, OCR service, and model server.
- Model-routing and scoring consistency guardrails.
- Manual end-to-end operational validation with real service calls.

Parallel design track captured but not fully implemented yet:
- Code evaluation sandbox architecture (microVM/snapshot-based execution plan).

## 2) Original Plan Streams and Current Status

### A. OCR Pipeline (Core Priority)
Status: Substantially implemented and manually validated.

Done:
- GLM-OCR serving path established via vLLM + OCR microservice.
- Gemini OCR integrated as grading text source for subjective and mixed flows.
- Objective flow uses Gemini text plus GLM region metadata.
- OCR confidence/flagging and region metadata surfaced in submission OCR payload.

Open:
- Additional objective-heavy regression scenarios and dataset-wide benchmarking.
- Production-level retry/backoff tuning for transient model rate limits (initial implementation done; calibration remains).

### B. Rubric + Grading Workflow
Status: Implemented and validated.

Done:
- Assignment, rubric, submission, grade, and audit workflows active.
- Rubric approval gate enforced (grading blocked until approved rubric exists).
- Manual rubric upload flow and AI rubric generation flow both supported.
- Scoring granularity logic implemented (question-level, rubric-step-level, hybrid-code mode).
- Consistency normalization and issue tagging integrated.

Open:
- Broader quality calibration for strictness/fairness across varied subjects.
- Expanded test corpus for truncation and edge OCR failures.

### C. Worker/Queue Reliability
Status: Implemented and stabilized.

Done:
- Celery tasks bound to configured app and explicitly registered.
- Queue split in place (`ocr_queue`, `grading_queue`) with dedicated worker services.
- Task state transitions persist correctly in DB under normal paths.
- No-job-lost behavior improved vs. earlier unregistered-task drops.

Open:
- Additional resiliency tests for worker restart during long-running jobs.

### D. Docker/Runtime Operations
Status: Stabilized for local operation.

Done:
- Compose stack operational for backend, postgres, redis, workers, vLLM, OCR service.
- Healthchecks hardened for slim Python images (urllib probes instead of curl).
- Deterministic vLLM image path introduced (pinned base and transformers ref).
- Runtime model/env precedence issues diagnosed and fixed for repeatability.

Open:
- Optional startup optimizations for first-time model pull warm-up.

### E. Code Evaluator (MicroVM Agent Plan)
Status: Phase 1 persistence and API/worker are implemented; local/docker backends and shim retry are validated; microVM adapter boundary is integrated with fallback while full runtime remains pending.

Done:
- Detailed architecture and execution-flow plan drafted.
- State-machine scaffold added for evaluator lifecycle states.
- Typed execution contracts added for job request/result and testcase/I-O definitions.
- Environment definition modes captured (manifest, lockfile, image reference).
- Test authoring modes captured (instructor I/O, question+solution->tests, question->solution+tests).
- Optional Gemini quality-evaluation lane captured in contracts/prep docs.
- PostgreSQL schema models added for:
  - `code_eval_environment_versions`
  - `code_eval_approval_records`
  - `code_eval_jobs`
  - `code_eval_attempts`
- Alembic migration added for code-eval phase-1 schema (`002`).
- API routes added for environment versions, approval records, and code-eval jobs.
- Dedicated code-eval Celery queue routing and worker task skeleton added.
- Execution backend selector implemented (`local` and `docker`).
- Local backend validated with both terminal outcomes and testcase-level artifacts.
- Docker backend validated with both terminal outcomes and testcase-level artifacts.
- Docker execution switched to archive staging via Docker SDK to avoid worker-container path bind-mount mismatches.
- Environment lifecycle API hooks implemented:
  - `/code-eval/environments/versions/{id}/build`
  - `/code-eval/environments/versions/{id}/validate-publish`
- Environment build worker flow implemented with persisted logs and status transitions (`building` -> `ready`/`failed`).
- Job creation now enforces ready/frozen environment requirement before enqueue.
- Worker now supports deterministic shim retry orchestration with state transitions through `AI_ANALYZING` and `RETRYING_SHIM` when failures are interface-level.
- Execution selector now supports `microvm` with adapter metadata and controlled fallback to `local`/`docker`.

Open:
- Full microVM runtime integration (snapshot manager/vsock guest agent execution) is not implemented yet.
- Full isolated microVM runtime integration (snapshot manager/vsock guest agent execution) is not implemented yet; current `pilot_*` modes are delegated bridge paths.
- AI model-generated shim synthesis is not implemented yet (current retry policy is deterministic and limited to whitespace interface mismatches).
- Approval records are persisted, but automated AI artifact generation + dual-approval orchestration is not implemented yet.

## 3) Key Implementation Decisions (Must Remember)

1. OCR source-of-truth for grading text:
- Gemini OCR text is the downstream grading source for subjective/mixed.
- Objective submissions include GLM region metadata for confidence/layout context.

2. Rubric control policy:
- AI-generated rubrics are created with `approved=false`.
- Grading is blocked until rubric approval.

3. Coding scoring policy:
- For coding assignments, `scoring_policy.coding.rubric_weight` and `testcase_weight` are required and normalized.

4. SDK path strategy:
- Keep Gemini calls on SDK path in service code.
- Avoid ad-hoc fallback drift unless explicitly approved.

5. Environment precedence hardening:
- Docker Compose host env can override `.env`; this previously caused credential/model drift.
- Compose now prefers project-scoped variables for key model settings and API key injection.

6. Model compatibility:
- Not all models support identical optional config knobs.
- Structured generation config now avoids forcing `thinking_level` globally.

6b. Transient model error handling:
- Model calls now use explicit retry + exponential backoff + jitter for transient 429/5xx/resource exhaustion paths.
- API route for AI rubric generation returns clearer HTTP 503/502 messages for transient/permanent model failures.

7. JSON persistence behavior:
- In-place mutation of nested JSON in SQLAlchemy JSON columns is unreliable.
- For OCR corrections, deep-copy + reassign JSON payload before commit is required.

8. Validation methodology:
- E2E scoring tests must align assignment/rubric semantics with actual OCR output.
- Mismatched question/rubric design can look like pipeline failure when it is not.

9. Code evaluator standardization strategy:
- Instructor-facing flexibility is supported, but execution always normalizes to canonical environment spec + canonical testcase contract.
- Build/freeze once per assignment environment version, then run each submission in clean ephemeral clones for efficiency and isolation.
- Final code-evaluator persistence backend is PostgreSQL (proper DB), not lightweight local-only substitutes.
- Environment reuse is course-scoped with assignment-level overrides.
- AI-generated solution and test artifacts require separate approvals.
- Quality/evaluation config is mandatory per assignment with instructor-editable rubric dimensions.
- Default regrade policy is new submissions only unless explicit regrade is requested.

## 4) Significant Files Changed During This Workstream

Backend and services:
- `backend/app/services/genai_client.py`
- `backend/app/services/rubric_generator.py`
- `backend/app/services/grading_service.py`
- `backend/app/services/ocr_service.py`
- `backend/app/services/code_eval/state_machine.py`
- `backend/app/services/code_eval/contracts.py`
- `backend/app/services/code_eval/__init__.py`
- `backend/app/services/code_eval/execution_service.py`
- `backend/app/services/code_eval/shim_service.py`
- `backend/app/services/code_eval/microvm_executor.py`
- `backend/app/workers/celery_app.py`
- `backend/app/workers/code_eval_tasks.py`
- `backend/app/workers/ocr_tasks.py`
- `backend/app/workers/grading_tasks.py`
- `backend/app/api/v1/code_eval.py`
- `backend/app/api/v1/assignments.py`
- `backend/app/api/v1/submissions.py`
- `backend/app/models/__init__.py`
- `backend/app/schemas/__init__.py`
- `backend/alembic/versions/002_code_eval_phase1_schema.py`
- `backend/alembic/versions/003_assignment_publish_state.py`
- `ocr/layout.py`
- `ocr_service/requirements.txt`

Infra/config:
- `docker-compose.yml`
- `vllm/Dockerfile`
- `.env.example`
- `.env` (runtime-local updates over time)
- `backend/CODE_EVALUATOR_PREP.md`
- `runtime_bridge_service/server.py`
- `runtime_bridge_service/Dockerfile`
- `runtime_bridge_service/requirements.txt`
- `logs/code_eval_runtime_bridge_compose_smoke.ps1`
- `backend/app/services/code_eval/firecracker_runtime.py`
- `microvm_guest_agent/agent.py`
- `microvm_guest_agent/README.md`
- `backend/Dockerfile.microvm`
- `docker-compose.microvm.yml`
- `microvm/README.md`
- `logs/code_eval_firecracker_preflight.ps1`

Validation artifacts/logging:
- `logs/manual_scenarios_raw_2026-04-06.txt`
- `logs/code_eval_assignment_publish_gates_validation_2026-04-07.txt`
- `logs/code_eval_shim_retry_validation_2026-04-07.txt`
- `logs/code_eval_microvm_adapter_validation_2026-04-07.txt`
- `logs/code_eval_microvm_pilot_runtime_validation_2026-04-07.txt`
- `logs/code_eval_microvm_pilot_docker_policy_validation_2026-04-07.txt`
- `logs/code_eval_microvm_runtime_bridge_validation_2026-04-07.txt`
- `logs/code_eval_runtime_bridge_compose_smoke_2026-04-07.txt`
- `logs/code_eval_firecracker_vsock_validation_2026-04-07.txt`
- `logs/code_eval_firecracker_preflight_2026-04-07.txt`
- Repository memory notes in `/memories/repo/` capture durable lessons.

## 5) Manual Validation Summary (High-Value Results)

Validated successfully:
- Full assignment -> rubric -> approval -> upload -> OCR -> grading chain.
- Aligned rubric scenario produced expected full score.
- Intentional partial mismatch reduced score as expected.
- Unapproved rubric scenario correctly blocked grading.
- Duplicate upload guard correctly returned conflict.

Defect found and fixed:
- OCR correction path previously recorded audit but did not reliably persist nested OCR JSON edits.
- Fix applied in `backend/app/api/v1/submissions.py` (deep copy + assign-back).
- Regrade after correction now updates score according to edited OCR content.

## 6) Repository Cleanup Performed

Cleanup done:
- Root-level raw/manual JSON artifacts moved into organized folder:
  - `logs/manual_artifacts/`

Moved files:
- `.manual_e2e_ids.json`
- `.manual_e2e_ids_run2.json`
- `.manual_rubric_manual_payload.json`
- `.manual_rubric_manual_payload_run2.json`
- `.manual_rubric_payload.json`
- `.manual_rubric_payload_recheck.json`
- `.manual_rubric_payload_run2.json`
- `.vertex_probe_body.json`

## 7) What Is Done vs. What Is Next

Done now:
- Core OCR-grading pipeline is functioning in Docker with manual validated scenarios.
- Model/env drift and worker registration blockers are resolved.
- OCR correction persistence defect is fixed and regrade effect is confirmed.
- Explicit retry/backoff and clearer model-error surfacing are implemented for transient model failures.
- Raw run outputs are consolidated under `logs/`.
- Code-evaluator phase-1 DB/API/queue skeleton is now implemented with PostgreSQL persistence.
- Code-evaluator jobs now persist state transitions and attempts with executable backends (`local` and `docker`) selected by config.
- Live smoke run validated: assignment -> env version -> dual approvals -> submission -> code-eval job enqueue -> worker execution.
- Alembic state reconciled for existing local DB by one-time `alembic stamp 002` because schema existed without version table.
- API now enforces policy gates at runtime:
  - explicit quality config required for job creation,
  - required approved artifacts for AI-generated test authoring modes,
  - minimum testcase-class coverage gate (`happy_path`, `edge_case`, `invalid_input`) before `ai_tests` approval.
- Code-eval worker now supports opt-in local Python execution backend (development mode) with per-testcase artifacts persisted.
- Runtime validation now includes both terminal outcomes under local execution:
  - one `COMPLETED` job with full score and testcase-level pass artifacts,
  - one `FAILED` job with clear mismatch reason and testcase-level failure artifacts.
- Code-eval execution now supports backend selection (`local` or `docker`) through configuration.
- Code-eval execution selector now supports `microvm` adapter mode with configurable fallback (`local` or `docker`).
- Docker backend is implemented and validated using Docker SDK + archive staging (avoids container-path bind-mount issues).
- Docker mode runtime validated with terminal outcomes:
  - one `COMPLETED` job with full score and testcase-level pass artifacts,
  - one `FAILED` job with testcase mismatch artifacts and clear failure reason.
- MicroVM adapter mode validated in two control paths:
  - fallback-enabled run (`microvm` -> `local`) completed and persisted adapter/fallback metadata in attempt artifacts,
  - fallback-disabled run failed deterministically with explicit adapter-disabled error.
- MicroVM runtime mode validation added:
  - `pilot_local` run completed via adapter-ready delegated path (`executor=microvm_adapter`, `fallback_used=false`),
  - invalid runtime mode guard returned deterministic failure with explicit metadata (`reason=invalid_runtime_mode`).
- Pilot-docker policy validation added:
  - approved environment policy (`microvm_policy.allow_pilot_runtime=true`, `approved_by`) completed via adapter path,
  - missing policy blocked at job creation (`422`) with explicit policy requirement detail.
- Runtime-bridge validation added:
  - `runtime_bridge` mode completed via external bridge contract path (`reason=runtime_bridge_executed`),
  - missing bridge URL with fallback enabled completed via configured fallback backend (`reason=runtime_bridge_not_configured`, `fallback_used=true`).
- Environment build/freeze hooks validated:
  - pre-build publish validation fails as expected,
  - pre-build job creation is blocked,
  - build task transitions env to `ready` with a persisted `freeze_key`,
  - post-build publish validation passes and job creation succeeds.

Next recommended steps:
1. Add automated regression tests that mirror the validated manual scenarios (aligned, mismatch, unapproved-rubric, duplicate-upload, OCR-correction-regrade).
2. Expand objective-flow validation corpus and calibrate confidence/flag thresholds.
3. Extend microVM adapter boundary into real snapshot/vsock execution runtime.
4. Extend deterministic shim retry into model-assisted shim synthesis with explicit policy/audit controls.
5. Add a lightweight operations runbook (startup order, health checks, common failure signatures, recovery commands).

## 8) Operational Notes for Future Sessions

- First vLLM cold start can be significantly slow due to model pull/warm-up.
- Keep model and key values project-scoped to avoid host shell override surprises.
- Prefer preserving raw manual evidence logs in `logs/` for incident analysis and reproducibility.
