# Implementation Progress

Date: 2026-04-08

This document consolidates implementation progress across the full workstream so far (not only the most recent debugging cycles). It is based on the PRD, the plan iteration history, and all code and runtime validation work completed in this repository.

## 0) Session Changelog (Newest First)

Practice:
- For every meaningful implementation session, add a dated summary entry here first.
- Keep each entry concise (what changed, what was validated, what remains).
- Link to raw validation artifacts in `logs/` whenever available.

### 2026-04-14 — Code-Eval Hardening, Multi-Language Execution, and Rigorous Integration Testing

#### Overview

This session completed the production hardening of the code-eval pipeline. Work covers:
- Six new/rewritten code-eval service modules
- One new Alembic migration
- A complete rewrite of the integration test suite as a standalone no-xfail runner
- Four real bugs found and fixed through live testing (not hypothetical)
- Full multi-language validation: Python, C (gcc 14.2), C++ (g++ 14.2), Java (javac 21)
- AI shim real-Gemini path verified live

Final integration result: **20/20 tests passed, 0 failures, 0 xfails, 0 skips**.

---

#### New Files Created

| File | Purpose |
|---|---|
| `backend/app/services/code_eval/language_config.py` | Authoritative `language_config` parser and validator. Raises `ValueError` on any unknown key (no silent ignoring). Merges instructor overrides onto per-language profile defaults. |
| `backend/app/services/code_eval/language_profiles.py` | Per-language execution profiles: default compile flags, link flags, run flags, entrypoint style, timeout, and memory for Python, C (gcc), C++ (g++), Java. |
| `backend/app/services/code_eval/test_authoring_service.py` | AI-assisted testcase generation (mode 2: question+solution→tests, mode 3: question→solution+tests) and approval coverage validation (`CoverageError` with explicit min-class requirements). |
| `backend/app/services/code_eval/scoring_service.py` | `build_score_breakdown()` — aggregates attempt scores, quality weight, and total/max into a deterministic score breakdown dict. Previously missing from containers, causing `ModuleNotFoundError`. |
| `backend/alembic/versions/004_code_eval_grade_backref.py` | Migration adding `grade_id` FK column on `code_eval_jobs` (back-reference from job → grade) and adding `code_eval` to the `gradesource` enum. |
| `backend/tests/integration/run_rigorous.py` | Standalone integration test runner. 20 use cases, no pytest.xfail, no skips, raw JSON logged per test to `logs/raw/`. |
| `backend/tests/integration/test_live_system.py` | Pytest-based integration suite (33 test cases, complementary to rigorous runner — used for CI). |
| `backend/tests/code_eval/test_ai_shim_multilang.py` | Unit tests for shim service multi-language eligibility logic. |
| `backend/tests/code_eval/test_language_config.py` | Unit tests for `parse_language_config`: unknown key rejection, type validation, profile-default merging. |

---

#### Modified Files (diff stats)

| File | +lines / -lines | What changed |
|---|---|---|
| `backend/app/workers/code_eval_tasks.py` | +307 / −138 | Full lifecycle rewrite: grade write-back, structured transition logging, env version pre-check, **language_config validation gate** (see bug #4), shim_warning surfacing |
| `backend/app/services/code_eval/execution_service.py` | +450 / −346 | Real polyglot dispatch for C/C++/Java; try/except around parse_language_config in both local and docker backends; testcase_results init fix |
| `backend/app/services/code_eval/shim_service.py` | +300 / −227 | Real Gemini model call instead of deterministic string substitution; multi-language shim eligibility analysis |
| `backend/app/api/v1/code_eval.py` | +178 / −0 | Added `GET /environments/versions/{id}` endpoint; wired `test_authoring_service` into approval coverage validation; added test-authoring generation endpoints |
| `backend/app/models/__init__.py` | +6 / −0 | Exported `CodeEvalEnvironmentVersion`, `Grade`, `GradeSource` for use in task imports |
| `backend/app/services/code_eval/contracts.py` | +36 / −0 | Added missing `CodeEvalErrorCode` enum values; extended `QualityEvaluationConfig` with `model_name` |
| `backend/app/workers/code_eval_env_tasks.py` | +33 / −0 | Added deterministic freeze-key dedup: if a ready env with the same freeze_key already exists, second env version is updated to match rather than rebuilding |

---

#### Real Bugs Found and Fixed (in order of discovery)

**Bug 1: `scoring_service.py` missing from deployed containers**

- Symptom: All code-eval jobs returned `ModuleNotFoundError: No module named 'app.services.code_eval.scoring_service'` in worker logs — jobs never completed.
- Root cause: The file was planned in the architecture but never written.
- Fix: Implemented `scoring_service.py` with `build_score_breakdown()`, deployed to both `amgs-backend` and `amgs-worker-code-eval`.
- Impact: Unblocked the entire test suite.

**Bug 2: `quality_evaluation.mode="none"` rejected by API**

- Symptom: Integration test job submissions returned 422 Unprocessable Entity.
- Root cause: `QualityEvaluationMode` enum only defines `"disabled"`, `"rubric_only"`, `"rubric_and_heuristics"` — `"none"` is not valid.
- Fix: All tests corrected to use `"disabled"`. The API correctly rejects unknown enum values.
- Design decision: `"disabled"` is the canonical zero-quality mode; `"none"` never existed in the validated schema.

**Bug 3: JPEG hash dedup caused 409 for all students in classroom simulation**

- Symptom: UC16 (8-student classroom): only stu-A succeeded; B–H all got 409 Conflict on submission upload.
- Root cause: All students were uploading identical bytes (`\xff\xd8\xff\xe0` + 16 null bytes). The submission upload endpoint deduplicates by SHA-256 content hash — identical hash = same file = conflict.
- Fix: `create_submission()` now embeds `student_id.encode()` into the JPEG stub bytes, making every student's file hash unique.
- Design note: This is correct server behaviour (dedup prevents OCR re-processing of identical scans). The bug was in the test helper, not the server.

**Bug 4 (most significant): `language_config` unknown keys silently ignored — data-flow gap**

- Symptom: UC14 `test_unknown_language_config_key_rejected_at_job_create` — job COMPLETED despite `{"junk_key_must_fail": "boom"}` in `language_config`. Was masked with `pytest.xfail()`.
- Root cause traced through three layers:
  1. `execution_service._execute_local_backend` called `parse_language_config(request.environment.spec_json if hasattr(request.environment, "spec_json") else None, ...)`.
  2. `request.environment` is of type `EnvironmentSpec` (the job request's inline spec, populated from `"environment": {}` in the API body). `EnvironmentSpec` has no `spec_json` attribute — `hasattr` returned `False`.
  3. Parser received `None` → returned profile defaults → unknown keys in the actual DB-stored `spec_json` were never seen.
- Fix: The validation was moved to `code_eval_tasks.py` where the DB session is live:
  ```python
  env_version = db.get(CodeEvalEnvironmentVersion, job.environment_version_id)
  env_spec_json = env_version.spec_json if env_version else None
  try:
      parse_language_config(env_spec_json, job_language=request.language.value)
  except ValueError as cfg_err:
      # ... fail job with configuration_error before any execution starts
  ```
- This is now the **authoritative validation point** — fires unconditionally for every language, every job, before static analysis, before execution.
- Spot-check confirmed: job with `junk_key_must_fail` now returns `FAILED` with `error_code=configuration_error` and the exact invalid key listed in `error_message`.

---

#### Design Decisions Made

1. **Language config validation belongs in the task, not execution_service.**
   The reason: `execution_service` only receives a `CodeEvalJobRequest` (deserialized from `job.request_json`), which contains `environment: EnvironmentSpec` — a normalized contract object, not the raw instructor-authored `spec_json`. The raw `spec_json` lives in `CodeEvalEnvironmentVersion` which is only accessible with a DB session. The task is the only correct place to do this validation because it has the DB session and has loaded the job. This also means validation happens once (not once per backend implementation), avoiding the risk of one backend forgetting to validate.

2. **Fail-fast configuration errors before static analysis.**
   The language_config gate runs before the static analysis gate. Rationale: a misconfigured environment version will cause every single submission to fail — it should be surfaced immediately, not buried inside attempt artifacts. Instructors see `[configuration_error] Unknown keys in language_config: ['junk_key_must_fail']` in the job's `error_message` with the allowed key list.

3. **Compilers installed in the worker container, not via Docker-in-Docker.**
   For local execution backend, compilers (`gcc`, `g++`, `javac`) are installed directly in `amgs-worker-code-eval` via `apt-get`. This avoids Docker socket complexity for the local backend path and makes C/C++/Java execution work without network requirements. The docker backend (when `CODE_EVAL_EXECUTION_BACKEND=docker`) uses a separate container image per language.

4. **Integration test suite is a standalone Python script, not pytest.**
   `run_rigorous.py` uses no pytest machinery. Reasons: (a) pytest's `xfail`/`skip` mechanisms are too easy to abuse — a standalone asserting script has no such escape hatch; (b) raw HTTP exchanges can be logged to JSON files per test without pytest plugins; (c) test runs produce a machine-readable `integration_results.json` suitable for CI consumption. The pytest suite (`test_live_system.py`) still exists for CI integration where its JUnit output is useful.

5. **Unique JPEG stubs per student is a test requirement, not workaround.**
   The server's file dedup (SHA-256 before OCR) is correct and intentional — it prevents re-OCR-ing identical scans. Integration tests must simulate realistic file diversity. Each student's stub now encodes their student_id into the JPEG bytes.

6. **Grade write-back is non-fatal.**
   If the grade DB write fails, the job still transitions to `COMPLETED` and the error is logged with `[GRADE_WRITE_FAILED]`. This prevents a grade table constraint issue from blocking the grading pipeline entirely. The missing grade is surfaced in logs for operator recovery.

---

#### Integration Test Evidence

**Run ID:** `20260413T202301Z`
**Execution time:** ~82 seconds (8 students × Python + 5 concurrent + single C/C++/Java + all others)

```
UC1:  Python stdin (5 testcases)                    ✅ score=5.0 exact
UC1b: Grade write-back                              ✅ source=code_eval, total_score=1.0
UC2:  C fibonacci (gcc 14.2, 4 testcases)           ✅ score=4.0, fib(10)=55 correct
UC2b: C compile error → structured error_code       ✅ failure_reason contains "compile"
UC3:  C++ sort vector (g++ 14.2, 3 testcases)       ✅ score=3.0, sorted output exact
UC4:  Java FizzBuzz (javac 21, 2 testcases)         ✅ COMPLETED, FizzBuzz output exact
UC5:  Regrade policy 409 on duplicate               ✅ second job → 409
UC6:  Static analysis (subprocess/os/eval) ×3       ✅ all 3 variants blocked
UC7:  Partial scoring (2/4 testcases pass)          ✅ attempt.score=2.0, FAILED overall
UC9:  No grade for FAILED job                       ✅ GET /grade → 404
UC10: Missing entrypoint → FAILED                   ✅ error_message non-empty
UC11: 5 concurrent jobs                             ✅ 5/5 COMPLETED in 1.8s
UC12: Approval coverage gate                        ✅ under-coverage=422, full=approved
UC13: Infinite loop → timeout                       ✅ failure_reason contains "timeout"
UC14: Bad language_config → configuration_error     ✅ FAILED (no xfail, no masking)
UC15: Output truncation                             ✅ output_truncated=True for >512KB
UC16: 8-student classroom                           ✅ exactly 4 COMPLETED, 4 FAILED, 9.4s
UC17: Env guards inactive=409, cross-course=422     ✅
UC18: AI shim — real Gemini verified                ✅ shim_generation_enabled=True, no mock
UC19: API 404/422/409 robustness                    ✅
```

Raw logs (full HTTP request/response per test): `backend/tests/integration/logs/raw/` (20 JSON files).
Summary: `backend/tests/integration/logs/integration_results.json`.

---

#### Load Test Summary

- **5 concurrent Python jobs** (UC11): 5/5 COMPLETED in **1.8 seconds** wall time. Worker concurrency = 2.
- **8-student classroom** (UC16): 4 passing + 4 failing students, 4 concurrent workers, **9.4 seconds** total. Previous runs took 29s because of hash-collision 409s forcing serial retries.

---

#### What Remains Open

| Item | Status | Notes |
|---|---|---|
| `SAWarning` on FK cycle between `assignments` and `code_eval_environment_versions` | Non-blocking | Appears during `drop_all` in tests. Fix: apply `use_alter=True` to the involved ForeignKey. |
| C/C++/Java compilers in worker are ephemeral | Transient | Installed via `docker exec apt-get`. The Dockerfile for `amgs-worker-code-eval` needs updating to bake them in permanently. |
| Docker execution backend (separate container per language job) | Not tested this session | Local backend is the tested path. Docker backend has the same fix applied but needs a comparable test run. |
| Full microVM runtime integration | Not yet | Pending Linux KVM host. Windows Docker Desktop cannot support Firecracker. |
| AI shim model-assisted synthesis (not just retry eligibility) | Partial | `shim_service.py` now makes real Gemini calls for code wrapping. Full multi-language shim coverage not yet validated end-to-end for C/Java. |


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

### 2026-04-08

- Added automated code-eval regression tests under `backend/tests/code_eval/` for:
  - static-analysis gate behavior,
  - shim retry decision logic (deterministic and mocked AI patch path),
  - quality scoring lane (weighted scoring + model-unavailable fallback),
  - polyglot local command resolution (Python/C/C++/Java).
- Executed test suite and validated all new tests passing (`11 passed`).
- Re-ran API smoke validations for policy/build flows:
  - static analysis gate end-to-end (`logs/validate_api_static_gate.ps1`),
  - environment build/publish readiness (`logs/validate_env_build_api.ps1`).
- Re-ran Firecracker preflight in forced microVM mode and confirmed host-level blocker remains on Windows Docker Desktop (`firecracker_binary_exists`, `snapshot_*_configured`, `kvm_available` unmet in runtime preflight).
- Added Windows-now/Linux-later deployment handoff docs and tooling:
  - `microvm/LINUX_DEPLOYMENT_GUIDE.md`
  - `microvm/scripts/linux_host_preflight.sh`
  - updated `microvm/README.md` with preflight + transition guidance.

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
- `microvm/LINUX_DEPLOYMENT_GUIDE.md`
- `microvm/scripts/linux_host_preflight.sh`
- `logs/code_eval_firecracker_preflight.ps1`

Code-eval safety/quality services and tests:
- `backend/app/services/code_eval/static_analysis.py`
- `backend/app/services/code_eval/quality_service.py`
- `backend/tests/code_eval/test_static_analysis.py`
- `backend/tests/code_eval/test_shim_service.py`
- `backend/tests/code_eval/test_quality_service.py`
- `backend/tests/code_eval/test_execution_polyglot_commands.py`
- `logs/validate_api_static_gate.ps1`
- `logs/validate_env_build_api.ps1`

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
- `logs/code_eval_firecracker_preflight_2026-04-08.txt`
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
1. ~~**Bake compilers into the worker Dockerfile**~~ ✅ Done — gcc 14.2, g++ 14.2, javac 21 baked in.
2. ~~**Google Classroom integration**~~ ✅ Done — full ingest → grade → sync-draft → release loop verified live.
3. Keep daily dev validation on Windows in default backend mode (`local`) and avoid forcing `firecracker_vsock` on Docker Desktop hosts.
4. Add/maintain Linux KVM staging validation lane using `microvm/scripts/linux_host_preflight.sh` + `microvm/scripts/firecracker_smoke.sh` before release.
5. Resolve the `SAWarning` FK cycle (`assignments` ↔ `code_eval_environment_versions`) by applying `use_alter=True` to the FK in `004_code_eval_grade_backref.py`.
6. Implement Frontend Classroom UI — sync controls, submission triage list, grade review dashboard.
7. Production deployment — push `amgs-worker-code-eval:latest` to registry, configure `google_auth/` volume on server, CI/CD pipeline.

## 8) Operational Notes for Future Sessions

- First vLLM cold start can be significantly slow due to model pull/warm-up.
- Keep model and key values project-scoped to avoid host shell override surprises.
- Prefer preserving raw manual evidence logs in `logs/` for incident analysis and reproducibility.
- Google Classroom OAuth: `credentials.json` must be the Desktop App type (not service account). Token is generated by running `backend/app/services/get_classroom_token.py` locally. The `google_auth/` directory is volume-mounted into the backend container — restart is required after generating `token.json` for the first time.
- Grade write-back to Classroom only works for coursework with `associatedWithDeveloper=True`. Use `backend/app/services/google_auth/create_api_assignments.py` to create API-owned assignments. Manually created assignments in the Classroom UI cannot have grades pushed by our app (Google policy).

---

### 2026-04-14 — Stream 1+2 Hardening: Worker Compiler Bake-In + Google Classroom Integration

#### Overview

This session completed two infrastructure streams that were left as "next steps" after the 2026-04-14 code-eval hardening session:

- **Stream 1**: Baked `gcc`, `g++`, `javac` permanently into a dedicated worker Docker image. Updated worker concurrency to 4. Validated real C, C++, and Java job execution end-to-end.
- **Stream 2**: Implemented and fully validated Google Classroom integration — submission ingestion from Drive, draft grade sync, and grade release to students. Verified with a real Classroom course, real student submission, and confirmed `state=RETURNED` + `assignedGrade` visible in the Classroom API.

Final result: **16/16 infrastructure checks + 20/20 grade-sync E2E checks, 0 failures.**

---

#### New Files Created

| File | Purpose |
|---|---|
| `backend/Dockerfile.worker` | Dedicated worker image with gcc/g++/javac baked in at build time |
| `backend/app/api/v1/classroom.py` | 5 REST endpoints: auth-status, ingest, sync-draft, release, status |
| `backend/app/services/classroom_sync.py` | OAuth management, Drive ingestion, draft/assigned grade push, grade release |
| `backend/app/services/get_classroom_token.py` | Local OAuth flow helper — runs on host to generate `token.json` |
| `backend/app/services/google_auth/create_api_assignments.py` | Creates Classroom assignments via API (required for grade write-back) |
| `backend/app/services/google_auth/list_classroom.py` | Lists coursework and submissions for a given course |
| `backend/tests/integration/verify_stream1_stream2.py` | E2E test — compiler bake-in, concurrency, + all 5 Classroom route schemas |
| `backend/tests/integration/test_classroom_e2e.py` | Auth + ingestion E2E against real Classroom course |
| `backend/tests/integration/test_grade_sync_e2e.py` | Full 10-step grade sync loop with real GCP API verification |

#### Modified Files

| File | Change |
|---|---|
| `docker-compose.yml` | Worker now builds from `Dockerfile.worker`; concurrency 2→4; `google_auth/` dir mount; uploads volume added to worker |
| `backend/app/main.py` | Registered `classroom.router` under `/api/v1` prefix |
| `backend/app/config.py` | Added `google_credentials_file`, `google_token_file`, `google_classroom_default_course_id`; paths updated to `google_auth/` subdir |
| `.env.example` | Documented all Google Classroom OAuth env vars |

---

#### Stream 1: Worker Dockerfile Hardening

**Problem**: The code-eval worker used the same image as the backend API, which had no compilers installed. C, C++, and Java jobs would fail silently or fall back to the AI shim.

**Solution**: Created `backend/Dockerfile.worker` that inherits from the backend base image and adds:
```dockerfile
RUN apt-get update -qq && \
    apt-get install -y --no-install-recommends gcc g++ default-jdk-headless && \
    rm -rf /var/lib/apt/lists/*
```

**Verification** (S1-C in `verify_stream1_stream2.py`):
- `gcc (Debian 14.2.0-19) 14.2.0` ✅
- `g++ (Debian 14.2.0-19) 14.2.0` ✅
- `javac 21.0.10` ✅
- Real C fibonacci job → `COMPLETED` (job=`754d9cf3`) ✅
- Real C++ sum job → `COMPLETED` (job=`8e5aa3a9`) ✅
- Real Java doubler job → `COMPLETED` (job=`73e4c70d`) ✅
- Celery concurrency confirmed at `-c 4` ✅

---

#### Stream 2: Google Classroom Integration

**Architecture**:
- `classroom_sync.py` manages the full OAuth lifecycle using file-based tokens (`token.json`). On expiry, the refresh token is used automatically; a new browser flow is only needed if the refresh token is revoked.
- Submission ingestion (`ingest_course_submissions`): pages through all `TURNED_IN` student submissions, downloads the primary Drive attachment, SHA-256 deduplicates, creates `Submission` rows in the AMGS DB, and enqueues OCR.
- Draft grade push (`push_draft_grades_bulk`): for each submission with an active `Grade` row, calls `studentSubmissions.patch(updateMask="draftGrade")`. Grades are visible to teachers but not students.
- Grade release (`release_grades_bulk`): calls `studentSubmissions.patch(updateMask="assignedGrade")` then `studentSubmissions.return_(id=...)`. This makes grades visible to students and transitions submissions to `RETURNED` state.

**Key Design Decisions**:

1. **Directory volume mount** — replaced individual file bind-mounts (`credentials.json`, `token.json`) with a single directory mount (`./google_auth:/app/.../google_auth`). Docker creates stub directories for individual file mounts if the file doesn't exist yet; a directory mount avoids this.

2. **Credential prefix stripping** — `_get_submission_meta()` strips `classroom-` prefix from `course_id` if present, for backward compatibility with older AMGS assignments.

3. **Explicit `assignment_id` routing in ingest** — `ingest_course_submissions` now accepts an optional `assignment_id` parameter. The API endpoint passes the URL path `assignment_id` so submissions are always created under the correct AMGS assignment, not whatever first matches by `classroom_id` in the DB. This was critical for repeatability in multi-run tests.

4. **`associatedWithDeveloper` policy** — Classroom API only permits `draftGrade`/`assignedGrade` PATCH on coursework created by the same GCP project. Manually created assignments in the UI cannot have grades pushed back. Use `create_api_assignments.py` to create coursework through the API. This is a hard Google platform policy, not a bug. Documented in operational notes.

5. **`return_()` fix** — The `return_()` Classroom API method requires `id` as a path parameter (not in the body). Fixed from `body={"ids": [sub_id]}` to `id=sub_id, body={}`.

---

#### End-to-End Verification Results

**`verify_stream1_stream2.py`** — 16/16 checks, 18.8s, exit 0:

| Check | Result |
|---|---|
| gcc in worker image | ✅ `14.2.0` |
| g++ in worker image | ✅ `14.2.0` |
| javac in worker image | ✅ `21.0.10` |
| Celery concurrency = 4 | ✅ |
| C fibonacci → COMPLETED | ✅ |
| C++ sum → COMPLETED | ✅ |
| Java doubler → COMPLETED | ✅ |
| 5/5 classroom routes in OpenAPI | ✅ |
| auth-status schema valid | ✅ |
| /ingest → 404 (not 500) for unknown | ✅ |
| /status → counts correct | ✅ |
| /sync-draft idempotent, no crash | ✅ |

**`test_grade_sync_e2e.py`** — 20/20 checks, 24.1s, exit 0 (real GCP calls, real student submission):

| Check | Subjective | Code |
|---|---|---|
| Student submission in Classroom | ✅ | ✅ |
| AMGS assignment created | ✅ | ✅ |
| Ingest: ingested=1 | ✅ | ✅ |
| Status: graded=0 pre-grade | ✅ | ✅ |
| Grade inserted (82/75 out of 100) | ✅ | ✅ |
| Status: graded=1 post-grade | ✅ | ✅ |
| sync-draft: pushed=1 | ✅ | ✅ |
| draftGrade verified in Classroom API | ✅ `82` | ✅ `75` |
| release: released=1 | ✅ | ✅ |
| state=RETURNED + assignedGrade visible | ✅ `82` | ✅ `75` |

---

#### Bugs Fixed in Production Code

| Bug | File | Fix |
|---|---|---|
| `return_()` missing `id` path param → `Missing required parameter "id"` | `classroom_sync.py` | Changed `body={"ids": [sub_id]}` to `id=sub_id, body={}` |
| `ingest_course_submissions` always picked first assignment with matching `classroom_id` | `classroom_sync.py`, `classroom.py` | Added `assignment_id` param; endpoint passes URL ID explicitly |
| PATCH 404 from Classroom: `course_id` stored as `classroom-<id>` | `classroom_sync.py` | Strip `classroom-` prefix in `_get_submission_meta` |
| OAuth scope missing `courses.readonly` | `classroom_sync.py` | Added to `_SCOPES` list |
| `/build` endpoint required JSON body even though all fields are optional | `verify_stream1_stream2.py` test | Passed `{"triggered_by": "s1-e2e-test"}` |
| Rubric creation used wrong path (`POST /rubrics` vs `POST /rubrics/{assignment_id}`) | `verify_stream1_stream2.py` test | Fixed path + `content_json` with coding scoring policy |
| Job submission used flat body instead of nested `request` object | `verify_stream1_stream2.py` test | Matched schema from `run_rigorous.py` |


