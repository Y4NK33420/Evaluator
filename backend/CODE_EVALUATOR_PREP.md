# Code Evaluator Preparation (Phase 0)

Date: 2026-04-06

This file captures the initial preparation work for the planned microVM-based code evaluator track.

## Objectives (updated)

The code evaluator must be both efficient and robust:
- Reuse frozen assignment environments instead of rebuilding per submission.
- Keep strict isolation and deterministic scoring.
- Support multiple instructor authoring modes for tests.
- Support optional Gemini-based code-quality assessment with standardized rubric output.
- Use proper PostgreSQL persistence as the source of truth for jobs, attempts, artifacts, and approvals.

## What is prepared now

1. Core lifecycle state machine primitives:
- `backend/app/services/code_eval/state_machine.py`
- States implemented:
  - `QUEUED`
  - `EXECUTING_RAW`
  - `AI_ANALYZING`
  - `RETRYING_SHIM`
  - `FINALIZING`
  - `COMPLETED`
  - `FAILED`
- Transition validation helpers:
  - `can_transition(...)`
  - `validate_transition(...)`

2. Execution contracts (typed request/result models):
- `backend/app/services/code_eval/contracts.py`
- Includes:
  - runtime language enum (`python`, `cpp`, `c`, `java`)
  - test case spec and I/O modes (`stdin`, `args`, `file`)
  - standardized environment specification modes
  - testcase authoring plan modes
  - quality evaluation config contract
  - execution quotas (timeout, memory, output cap, network flag)
  - job request and result contracts

3. Package export entrypoint:
- `backend/app/services/code_eval/__init__.py`

4. Phase-1 persistence and API/queue skeleton:
- SQLAlchemy entities added for environment versions, approvals, jobs, and attempts.
- Alembic migration added: `backend/alembic/versions/002_code_eval_phase1_schema.py`
- API routes added: `backend/app/api/v1/code_eval.py`
- Worker task skeleton added: `backend/app/workers/code_eval_tasks.py`
- Execution adapter boundary added with deterministic stub:
  - `backend/app/services/code_eval/execution_service.py`
- Policy gates implemented in API:
  - mandatory explicit `quality_evaluation` on job creation
  - approval prerequisites for AI-generated artifacts by authoring mode
  - testcase-class coverage gate for `ai_tests` approval

5. Local execution backend (development mode):
- `execution_service.py` now supports opt-in Python testcase execution using isolated temporary workdirs per testcase.
- Enabled via `CODE_EVAL_ENABLE_LOCAL_EXECUTION=true` (currently wired for `worker-code-eval` in compose).
- Persists testcase-level artifacts (stdout/stderr/exit/score) into `code_eval_attempts.artifacts_json`.
- Current limitation: this is not yet containerized/microVM isolated; treat as controlled-dev backend only.

6. Docker execution backend (intermediate isolation mode):
- Backend selector added: `CODE_EVAL_EXECUTION_BACKEND=local|docker|microvm`.
- Docker mode uses Docker SDK over mounted socket (no host-path bind dependency for testcase staging).
- Source/testcase files are uploaded into ephemeral containers via archive staging before execution.
- Runtime now supports validated terminal outcomes in docker mode (`COMPLETED` and `FAILED`) with testcase artifacts persisted.

6b. MicroVM adapter boundary (fallback-capable integration step):
- Added adapter module: `backend/app/services/code_eval/microvm_executor.py`.
- `microvm` can now be selected in backend config (`CODE_EVAL_EXECUTION_BACKEND=microvm`).
- Runtime mode controls are now available:
  - `pending` (default non-executing adapter mode)
  - `pilot_local` / `pilot_docker` (adapter-ready delegated pilot paths)
- Runtime bridge mode added:
  - `runtime_bridge` (external HTTP runtime contract execution path)
  - bridge settings: URL, timeout, TLS verify, optional bearer auth
- Firecracker snapshot/vsock mode added:
  - `firecracker_vsock` (snapshot restore + resume + vsock guest-agent execution path)
  - requires configured firecracker binary, snapshot vmstate/mem files, `/dev/kvm`, and vsock support
  - runtime preflight endpoint available: `GET /code-eval/runtime/preflight`
- Optional local reference runtime bridge service added for reproducible validation:
  - `runtime_bridge_service/server.py`
  - compose service: `runtime-bridge` (port `8099`)
  - bridge internal executor modes now available:
    - `local_reference` (in-service execution)
    - `microvm_transport` (forward to external isolated runtime endpoint)
  - bridge runtime introspection endpoint:
    - `GET /runtime/status`
- Controlled fallback is implemented for continuity:
  - `CODE_EVAL_MICROVM_ALLOW_FALLBACK=true|false`
  - `CODE_EVAL_MICROVM_FALLBACK_BACKEND=local|docker`
- Invalid runtime mode configuration now fails deterministically with explicit adapter metadata.
- Attempt artifacts now preserve microVM adapter decision metadata even when fallback executes the testcase run.
- Pilot runtime policy gate now enforced at job creation when backend is `microvm` with `pilot_*` mode:
  - `spec_json.microvm_policy.allow_pilot_runtime=true`
  - `spec_json.microvm_policy.approved_by` (non-empty)
- Pilot-docker preflight now requires explicit image reference at job creation (request or env spec), reducing late runtime pull failures.
- Runtime introspection endpoint added: `GET /code-eval/runtime/status`.
  - includes firecracker readiness hints:
    - `microvm.firecracker_snapshot_configured`
    - `microvm.firecracker_vsock_port`
    - `microvm.firecracker_preflight_ready`
    - `microvm.firecracker_preflight_issues`

7. Environment build/freeze orchestration hooks:
- API endpoint added to enqueue environment builds:
  - `POST /code-eval/environments/versions/{id}/build`
- API endpoint added to check publish readiness:
  - `POST /code-eval/environments/versions/{id}/validate-publish`
- Worker task added:
  - `backend/app/workers/code_eval_env_tasks.py`
- Build flow now persists status transitions and logs:
  - `building` -> `ready` (with `freeze_key`) or `failed`
- Job creation now requires environment status `ready` and non-empty `freeze_key`.

8. Assignment publish workflow integration:
- Assignment publish validation endpoint added:
  - `POST /assignments/{assignment_id}/validate-publish`
- Assignment publish endpoint added:
  - `POST /assignments/{assignment_id}/publish`
- Publish now enforces:
  - approved rubric exists
  - code assignments must bind a ready, active environment with non-empty `freeze_key`
- Assignment publish state is persisted with bound environment version metadata.

9. AI analyzing + shim retry execution path (deterministic policy):
- Worker transitions now run through `AI_ANALYZING` and `RETRYING_SHIM` for eligible failures.
- Shim retry eligibility is strictly gated to interface-level whitespace mismatches.
- Non-shimmable failures (exit-code/runtime/logic mismatch) skip retry and finalize as failed.
- Shim decisions are persisted in final result payload for auditability.

## Why this is useful now

- Gives a stable state vocabulary for DB schema/API/worker implementation.
- Reduces ambiguity before adding microVM orchestration code.
- Allows future worker code to enforce transition legality from day one.
- Encodes instructor-facing authoring variability while keeping internal execution standardized.

## Standardized instructor input modes

## Confirmed policy decisions (locked)

1. Environment reuse policy:
- Reusable per course with assignment-level overrides.

2. Approval policy for AI-generated assets:
- Separate approvals are required (solution and tests independently).

3. Quality configuration policy:
- Mandatory per-assignment configuration.

4. Quality rubric authoring policy:
- Instructor-editable dimensions are allowed.
- Rubric may be provided directly by instructor or AI-generated (approval required).

5. Regrade policy:
- Only new submissions are processed by default.
- Historical submissions are regraded only on explicit regrade request.

### A) Environment definition modes

All instructor input is normalized into an internal `EnvironmentSpec` and frozen to an assignment version.

Supported modes:
- `manifest`: instructor provides runtime + packages in structured key/value schema.
- `lockfile`: instructor provides lockfile content (or equivalent) for deterministic build.
- `image_reference`: instructor references a prebuilt base image/snapshot.

Internal policy:
- Build once per assignment environment version.
- Freeze to immutable snapshot/image (`freeze_key`).
- Execute each submission in an ephemeral clone of that frozen environment.
- Destroy clone after each run.

### B) Test authoring modes

Supported modes:
- `instructor_provided_io`: instructor supplies direct testcases and expected outputs.
- `question_and_solution_to_tests`: instructor gives question + reference solution; AI drafts tests/script; instructor approves.
- `question_to_solution_and_tests`: instructor gives only question; AI drafts solution and tests; instructor approval required before grading.

Normalization policy:
- All paths converge into canonical `TestCaseSpec[]` with explicit weights.
- No execution starts until required approvals are recorded.

### C) Code quality assessment mode

Optional quality lane uses Gemini with structured rubric scoring:
- `disabled`
- `rubric_only`
- `rubric_and_heuristics`

Recommended weighting (configurable by instructor/course policy):
- correctness score from testcase engine
- quality score from Gemini rubric dimensions
- combined score via deterministic weighted aggregation

## Planned runtime flow (v1)

1. `QUEUED`
- Job persisted with normalized environment spec + canonical testcase set.

2. `EXECUTING_RAW`
- Run in ephemeral clone of frozen assignment environment.

3. `AI_ANALYZING` (only on eligible failures)
- Model decides if failure is interface/format mismatch vs logic error.

4. `RETRYING_SHIM`
- Apply AI shim in fresh clone and re-run.

5. `FINALIZING`
- Aggregate testcase score deterministically.
- Optionally run quality evaluation lane and combine scores.

6. `COMPLETED` or `FAILED`
- Persist artifacts, logs, score breakdown, and audit metadata.

## Not implemented yet (next phase)

- Full microVM/snapshot execution runtime integration (adapter boundary exists; snapshot manager + vsock/guest execution pending).
- Vsock/guest-agent protocol integration.
- Snapshot manager hooks.
- AI model-generated shim synthesis/execution path.
- Instructor approval workflow automation for AI-generated solution/test bundles (records exist, orchestration pending).
- Quality rubric authoring and score-weight policy endpoints.

## Recommended next implementation order

1. Add environment freeze/build orchestration APIs and persist canonical version metadata (`freeze_key` ownership and publish validation).
2. Integrate real microVM/snapshot runtime behind current adapter boundary (replace fallback-only behavior).
3. Extend deterministic shim retry into model-assisted shim synthesis with explicit approval/audit controls.
4. Add quality-evaluation lane execution and deterministic combined score output in finalization stage.
5. Expand regression tests for policy gates and execution artifacts across local/docker/microvm/shim-retry paths.

## Operational bootstrap note (existing local DBs)

If the local database was previously initialized through app startup `create_all`,
core tables/enums may already exist without an `alembic_version` row.

In that case, do a one-time stamp before future upgrades:

```bash
docker compose exec backend alembic stamp 002
```

Then continue normal migration flow from subsequent revisions:

```bash
docker compose exec backend alembic upgrade head
```

## Open questions to resolve before Phase 1 execution

1. Environment freezing backend for v1:
- Docker image freezing first, then Firecracker snapshots later, or direct Firecracker now?

Recommendation:
- Start with Docker image freeze for v1 to ship faster and validate lifecycle semantics.
- Keep the execution adapter boundary clean so Firecracker can replace the backend without changing API/state logic.
- Add a compatibility target milestone for Firecracker once job/state/approval flows are stable.

2. Approval policy for AI-generated assets:
- Resolved: dual approval is required.

3. Quality weight policy:
- Resolved: per-assignment mandatory config.

Implementation note:
- Enforce presence of quality config at assignment publish time.
- Allow weight to be set to 0 when instructor wants correctness-only but still requires explicit intent.

4. Regrade behavior when rubric/tests change:
- Resolved: only new submissions by default unless explicit regrade requested.

5. Testcase quality gate before approval:
- Should approval require minimum testcase classes (happy path, edge cases, invalid input, stress)?

Recommendation:
- Yes, enforce a minimum class coverage gate before instructor approval is accepted.
- Start with required classes: happy path, edge case, invalid input.
- Make stress optional unless assignment has an explicit performance objective.

6. Environment profile strategy:
- Predefined official profiles only, or profiles + custom option?

Recommendation:
- Provide predefined official profiles (e.g., `python-basic`, `cpp17`, `java17`) plus a controlled custom profile option.
- Custom profiles should require freeze/build validation and explicit ownership metadata.
