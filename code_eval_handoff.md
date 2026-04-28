# Code Eval Feature Handoff

Date: 2026-04-13
Audience: Incoming coding agent and maintainers
Scope: Code-evaluation subsystem only (not full OCR/grading product)

This document is a complete handoff for the code-eval stream. It is structured in two major parts:

1. Original goal and requirements (what the feature was supposed to do, step by step).
2. Rigorous implementation account (what was actually built, validated, and why each key decision was taken).

---

## 1) Original Goal and Requirement Baseline

## 1.1 Product-level intention (from PRD + planning)

The code-eval feature exists to grade code submissions in a deterministic, auditable, and secure way while fitting current Windows-based development constraints and preserving a migration path to stricter Linux/KVM microVM isolation.

High-level objectives:

- Evaluate student code against instructor-defined testcases.
- Keep execution isolated and resource-limited.
- Guarantee deterministic scoring and reproducible outcomes.
- Persist full audit metadata (attempt-by-attempt, including retries and artifacts).
- Support multiple authoring modes for tests and environment definitions.
- Support optional AI-assisted retry for specific interface-level failures.
- Enforce explicit publish and approval gates before production usage.

## 1.2 Functional requirements (step-by-step lifecycle requirements)

The original required behavior can be expressed as a strict sequence.

### Step 1: Assignment context and environment versioning

- A code assignment must bind to a versioned execution environment.
- Environment versions must be immutable once frozen (via freeze key semantics).
- Reuse policy: course-level reuse with assignment-level overrides.

### Step 2: Environment definition normalization

Instructor input may come as:

- manifest
- lockfile
- image reference

But internal execution must normalize this to canonical environment metadata.

### Step 3: Environment build/publish gate

- Jobs must not run on unready environments.
- Environment version must be in ready state and have non-empty freeze_key.
- Publish readiness validation must fail fast when prerequisites are missing.

### Step 4: Test authoring normalization

Supported authoring modes:

- instructor_provided_io
- question_and_solution_to_tests
- question_to_solution_and_tests

All modes must converge to canonical testcase contracts.

### Step 5: Approval policy for AI-generated artifacts

- AI-generated solution/test artifacts require approval before use.
- Approvals are independent (solution and tests are separate tracks).
- API policy gates must block execution when approval requirements are unmet.

### Step 6: Job creation policy gates

On job creation:

- quality_evaluation config is mandatory (even if disabled/0 weight).
- environment readiness and freeze requirements enforced.
- testcase minimum class coverage gates enforced for AI-generated tests.

### Step 7: Execution state machine

Job states must enforce legal transitions:

- QUEUED
- EXECUTING_RAW
- AI_ANALYZING
- RETRYING_SHIM
- FINALIZING
- COMPLETED
- FAILED

### Step 8: Runtime execution backends

Backend selection requirements:

- local backend for fast development and deterministic smoke tests.
- docker backend for stronger intermediate isolation.
- microvm adapter boundary for future strict runtime.

### Step 9: Isolation and quota policy

Execution quotas must be explicit and enforceable:

- timeout
- memory
- output size
- network disabled policy

### Step 10: Shim retry policy

- Retry only if failure is likely interface-level mismatch.
- Do not retry algorithmic/logic errors as if they were OCR/interface noise.
- Persist shim decision payload and retry artifacts for auditability.

### Step 11: Final scoring and result payload

- deterministic correctness score from testcase outcomes
- optional quality lane integration
- consistent score breakdown metadata in final_result_json
- attempt-level artifacts persisted for each run

### Step 12: Operations and observability

- runtime status endpoint with backend/microvm visibility
- preflight semantics for microVM readiness
- runbooks/scripts for repeatable smoke and incident recovery

## 1.3 Non-functional requirements

- Determinism: same input and environment should produce equivalent result.
- Auditability: every attempt and decision path must be queryable.
- Fail-fast policy: invalid config/missing prerequisites should fail early.
- Windows-first practicality now, Linux/KVM hard isolation later.
- No silent policy bypasses.

---

## 2) What Was Implemented (Chronological, With Rationale)

This section is intentionally rigorous. Each subsection includes:

- What changed
- Why the decision was taken
- What evidence/validation exists

## 2.1 Phase 0 foundation: state machine and contracts

What changed:

- Added state primitives and transition validation in backend/app/services/code_eval/state_machine.py.
- Added typed contracts in backend/app/services/code_eval/contracts.py.
- Exported code-eval package entrypoint in backend/app/services/code_eval/__init__.py.

Why:

- Prevent lifecycle drift and hidden invalid transitions.
- Force strong request/result typing across API and worker boundaries.
- Enable later backend swaps (local/docker/microvm) without changing domain contract.

Evidence:

- Preparation notes in backend/CODE_EVALUATOR_PREP.md.

## 2.2 Persistence and API skeleton (Phase 1)

What changed:

- Added DB schema + migration for phase-1 entities.
- Added code-eval API routes for environment versions, approvals, jobs.
- Added dedicated worker queue/task skeleton for code-eval execution lane.

Why:

- PostgreSQL is source-of-truth for jobs/attempts/audit.
- API and queue skeleton enables incremental implementation without fake flows.

Evidence:

- Alembic revision and operational note in backend/CODE_EVALUATOR_PREP.md.

## 2.3 Local and docker execution backends

What changed:

- Implemented local execution backend for controlled development.
- Implemented docker backend with archive staging via Docker SDK.
- Added backend selector for local|docker|microvm in settings/config.

Why:

- Windows development needed real execution now.
- Archive staging avoided worker-to-host path bind mismatch hazards.
- Intermediate docker isolation gives better parity than local subprocess only.

Evidence:

- Runtime validations documented in implementation progress.
- Testcases and artifacts persisted with pass/fail outcomes.

## 2.4 Environment build/freeze and publish gates

What changed:

- Added build enqueue endpoint for environment versions.
- Added publish readiness validation endpoint.
- Added env build worker with building -> ready/failed transitions and build logs.
- Enforced job creation requirement: ready env + freeze_key.
- Added assignment publish gate integration requiring approved rubric + bound ready env.

Why:

- Remove ambiguity between draft env specs and executable frozen environments.
- Prevent accidental execution against unvalidated environment state.

Evidence:

- Manual API smoke scripts in logs for static gate and env build flows.

## 2.5 Policy gates for approvals and test quality

What changed:

- Mandatory explicit quality_evaluation config enforced on job creation.
- Approval prerequisites for AI-generated assets enforced.
- Testcase class coverage gate for ai_tests approvals enforced.

Why:

- Make grading policy explicit, not implicit defaults.
- Avoid executing unapproved AI-generated artifacts.
- Increase safety floor for generated tests.

Evidence:

- API behavior validated in manual smoke scripts and tests.

## 2.6 Shim retry orchestration and deterministic boundaries

What changed:

- Worker supports EXECUTING_RAW -> AI_ANALYZING -> RETRYING_SHIM path.
- Non-shimmable failures skip retry and finalize failed.
- Shim decision persisted in final_result_json including reasons and failed testcase evidence.

Why:

- Interface mismatches can be recovered safely; logic bugs should not be disguised as recoverable noise.
- Auditability requires explicit reasoning payloads.

Evidence:

- Integration behavior validated through tests and live runs.

## 2.7 MicroVM adapter boundary + runtime bridge + preflight

What changed:

- Added microvm executor adapter and runtime modes.
- Added fallback policy when strict microVM path is unavailable.
- Added runtime_bridge mode and reference bridge service.
- Added runtime status endpoint and preflight endpoint with firecracker readiness hints.
- Added pilot policy gate for microVM pilot modes.

Why:

- Ship incremental value now while preserving future strict isolation architecture.
- Explicit fallback metadata avoids hidden execution mode ambiguity.

Evidence:

- Runtime bridge and pilot mode validations in logs and progress notes.

## 2.8 Scoring breakdown and language profile hardening

What changed:

- Added scoring service to produce explicit correctness/quality/total score breakdown.
- Added language profile presets and docker image selection guards.
- Added artifact integrity checks for snapshot metadata in publish validation path.

Why:

- Improve transparency and deterministic post-processing.
- Prevent accidental Python-image default for compiled languages.
- Enforce snapshot artifact integrity constraints when snapshot policy applies.

Evidence:

- Unit tests added for scoring, language profiles, and publish integrity checks.

## 2.9 Regression coverage and CI lane

What changed:

- Added broad code-eval tests for shim, scoring, language matrix, runtime behavior, lock semantics, and policy gates.
- Added windows-feasible CI workflow for code-eval regression subset.

Why:

- Keep rapid iteration safe while microVM path evolves.
- Enforce cross-platform regression signal.

Evidence:

- Tests documented as passing in implementation progress.

## 2.10 Real-model AI shim E2E hardening (critical latest work)

What changed:

- Added end-to-end real-model validation script: logs/validate_ai_shim_real_e2e.ps1.
- Script now logs raw request/response payloads step-by-step.
- Added strict-mode-safe property handling and robust summary extraction.
- Added scenario design that separates:
  - fixable interface mismatch case
  - non-fixable logic bug case
- Added parser fallback improvements for structured model responses.
- Added richer shim prompt payload (testcase contracts and I/O mismatch signals).
- Added model transient token handling for disconnect-style failures.
- Added guarded fallback adapter patch if model marks fixable but omits patch files.

Why:

- User requirement was explicit: real model calls only, full raw outputs, log every step, and keep fixing until working.
- Live model behavior showed practical failure modes not visible in mocked tests:
  - model transport disconnects
  - fixable classification without concrete patch payload
  - fragile parse assumptions

Evidence:

- Raw run logs under logs/code_eval_ai_shim_real_e2e_*.txt.
- Confirmed successful lifecycle in logs/code_eval_ai_shim_real_e2e_20260408032821.txt:
  - fixable scenario: FAILED raw attempt -> AI_ANALYZING -> RETRYING_SHIM -> COMPLETED
  - attempt_count=2
  - shim_eligible=true, shim_strategy=ai_generated_patch
  - model and prompt_hash captured
  - logic bug scenario remained FAILED and non-fixable

---

## 3) Detailed Decision Ledger (What and Why)

This section captures the most consequential decisions and rationale.

1. Canonical contracts before runtime implementation
- Decision: define state machine + contracts first.
- Why: avoids API/worker divergence and untyped payload drift.

2. PostgreSQL first-class persistence
- Decision: jobs/attempts/results in DB, not ephemeral queue-only state.
- Why: auditability and no-job-lost recovery.

3. Explicit policy gates in API
- Decision: block early for quality config, approvals, and env readiness.
- Why: fail-fast is safer than late worker failure after enqueue.

4. Local + docker before strict microVM completion
- Decision: provide runnable Windows-feasible path now.
- Why: unblock implementation, tests, and product iteration while microVM path matures.

5. MicroVM adapter boundary with explicit fallback metadata
- Decision: keep microVM mode callable even when prerequisites absent.
- Why: preserve integration contract and observability while avoiding hard downtime in unsupported hosts.

6. Deterministic shim retry boundaries
- Decision: do not auto-retry logic bugs.
- Why: avoid false healing and grading corruption.

7. AI shim prompt enrichment using testcase contracts and source signals
- Decision: include explicit I/O mismatch evidence.
- Why: reduce misclassification of interface mismatch as logic bug.

8. Fallback adapter patch for "fixable but no patch returned"
- Decision: if model says fixable and failure pattern is interface-like, synthesize minimal safe adapter patch.
- Why: live models can classify correctly but omit patch payload; this closes a practical reliability gap.

9. Runtime workaround when backend image rebuild fails
- Decision: temporarily sync changed files with docker cp and restart containers.
- Why: Debian mirror DNS failures blocked rebuild; workaround enabled continued live validation.
- Note: this is operationally temporary, not a replacement for proper image rebuilds.

10. Capture model metadata in audit payload
- Decision: include model and prompt_hash in decisions/artifacts when available.
- Why: enables reproducibility and triage of model-dependent behavior.

---

## 4) Current Feature Status (As of this handoff)

## 4.1 Working now

- End-to-end job lifecycle with persisted attempts and artifacts.
- Environment build/readiness/publish gates.
- local and docker execution backends.
- microVM adapter modes with status/preflight visibility and fallback path.
- deterministic + AI-assisted shim analysis path.
- real-model AI shim E2E script with raw logs.
- score breakdown payloads.
- windows-feasible regression CI lane and expanded test coverage.

## 4.2 Explicitly proven in live run

From logs/code_eval_ai_shim_real_e2e_20260408032821.txt:

- Fixable scenario:
  - Job: 3d763f98-d254-4371-bfac-b1f106cdb346
  - Status: COMPLETED
  - attempt_count: 2
  - Raw fail followed by successful RETRYING_SHIM
  - Shim model: gemini-3.1-flash-lite-preview

- Logic-bug scenario:
  - Job: 17f574ad-07a9-4b52-87df-f2bda226d009
  - Status: FAILED
  - attempt_count: 1
  - Non-shimmable classification preserved

## 4.3 Known limitations and pending work

1. Full strict microVM runtime is still not complete end-to-end on Windows host.
2. Some operational flows were validated with docker cp sync due transient build-network issues.
3. AI-generated shim fallback currently targets specific interface mismatch class; broadening requires careful safety design.
4. Need sustained Linux/KVM staging lane to move from adapter/fallback to strict microVM production confidence.

---

## 5) File Map for Incoming Agent

Core code-eval domain:

- backend/app/services/code_eval/contracts.py
- backend/app/services/code_eval/state_machine.py
- backend/app/services/code_eval/execution_service.py
- backend/app/services/code_eval/shim_service.py
- backend/app/services/code_eval/microvm_executor.py
- backend/app/services/code_eval/scoring_service.py
- backend/app/services/code_eval/language_profiles.py

API and worker orchestration:

- backend/app/api/v1/code_eval.py
- backend/app/workers/code_eval_tasks.py

Model and parsing support:

- backend/app/services/genai_client.py
- backend/app/services/json_utils.py

Operations and validation:

- logs/validate_ai_shim_real_e2e.ps1
- logs/code_eval_ai_shim_real_e2e_20260408032821.txt
- microvm/CODE_EVAL_OPS_RUNBOOK.md
- implementation progress.md
- backend/CODE_EVALUATOR_PREP.md

Tests and CI:

- backend/tests/code_eval/
- .github/workflows/code_eval_windows_feasible.yml

---

## 6) Handoff Recommendations for the Next Agent

Priority order:

1. Stabilize image-based deployment parity:
- Rebuild backend image with latest shim/genai/json updates once network is stable.
- Confirm behavior without docker cp sync.

2. Expand real-model AI shim confidence suite:
- Add 3-5 additional interface mismatch fixtures (stdin/argv/file modes, minor OCR artifacts).
- Track retry success rate and false-positive logic healing rate.

3. Harden fallback patch synthesis:
- Add syntax guard and import dedup guard for synthesized patches.
- Keep fallback constrained to narrow signatures.

4. Advance microVM strict path on Linux/KVM:
- Use linux preflight + firecracker smoke scripts.
- Validate adapter metadata and strict non-fallback path in staging.

5. Improve observability:
- Add structured event logging for each state transition and shim decision branch.

---

## 7) Quick Verification Commands

Windows local verification:

1. Run code-eval tests:

```powershell
Set-Location d:/dev/DEP/backend
d:/dev/DEP/.venv/Scripts/python.exe -m pytest tests/code_eval -q
```

2. Runtime status check:

```powershell
curl.exe -sS http://localhost:8080/api/v1/code-eval/runtime/status
```

3. Real-model shim E2E run:

```powershell
Set-Location d:/dev/DEP
./logs/validate_ai_shim_real_e2e.ps1
```

---

## 8) Final Summary

The original feature intent was to deliver a deterministic, policy-gated, auditable code evaluator with secure isolation and optional AI-assisted recovery for interface-level failures. That intent has been substantially realized for Windows-feasible operation (local/docker) with a mature adapter boundary for microVM evolution, extensive tests, and proven real-model shim retry behavior in live end-to-end logs.

The remaining strategic gap is strict microVM production readiness on Linux/KVM and broader reliability hardening of AI shim generation beyond currently validated mismatch classes.
