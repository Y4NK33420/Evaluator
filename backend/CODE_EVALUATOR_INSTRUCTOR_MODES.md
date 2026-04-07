# Code Evaluator Instructor Input Modes

Date: 2026-04-06

This document defines standardized instructor-facing input modes that map to a single internal execution pipeline.

## 1) Environment definition modes

All modes normalize into an internal `EnvironmentSpec` and immutable assignment environment version.

Confirmed policy:
- Environment reuse is course-scoped by default with assignment overrides.

### Mode A: Manifest

Use when instructor wants explicit package/runtime declarations.

Example:
```json
{
  "mode": "manifest",
  "runtime": "python-3.11",
  "manifest": {
    "python": "3.11.9",
    "pip:numpy": "1.26.4",
    "pip:pandas": "2.2.2"
  }
}
```

### Mode B: Lockfile

Use when instructor already has deterministic dependency lock output.

Example:
```json
{
  "mode": "lockfile",
  "runtime": "python-3.11",
  "lockfile_content": "... lockfile text ..."
}
```

### Mode C: Image reference

Use when a curated prebuilt environment is available.

Example:
```json
{
  "mode": "image_reference",
  "runtime": "python-3.11",
  "image_reference": "registry.example.edu/codeeval/python-311:v3"
}
```

## 2) Test authoring modes

All modes normalize into canonical `TestCaseSpec[]` and weighted scoring metadata.

### Mode 1: Instructor-provided I/O

Instructor provides full testcase inputs and expected outputs.

### Mode 2: Question + instructor solution -> AI test generation

- Instructor provides question and trusted reference solution.
- AI produces testcase script/bundle.
- Instructor approval is required before grading starts.

### Mode 3: Question only -> AI solution + AI tests

- AI drafts both reference solution and tests.
- Instructor approval is mandatory before grading starts.
- Separate approvals are required for generated solution and generated tests.

Approval quality gate (recommended default):
- Approval should require minimum testcase classes:
  - happy path
  - edge case
  - invalid input
- Stress class can be optional unless performance is part of rubric.

## 3) Quality evaluation lane

Optional, separate from correctness scoring:
- Gemini evaluates style/readability/structure/error handling/documentation.
- Output must be structured JSON with per-dimension scores.
- Final total uses deterministic weighted combine between correctness and quality.

Confirmed policy:
- Quality config is mandatory per assignment.
- Instructors can edit dimensions/rubric.
- Rubric source can be either instructor-provided or AI-generated with approval.

## 4) Normalization and execution guarantees

- Build/freeze environment once per assignment version.
- Execute each submission in isolated ephemeral clone.
- No network by default, strict timeout/memory quotas.
- Persist full artifacts for audit:
  - source snapshot
  - execution logs
  - shim source (if used)
  - quality rubric output (if enabled)

Current implementation status:
- Backend selector is implemented (`local`, `docker`, and `microvm` adapter modes).
- Local and docker modes are both validated with pass/fail testcase artifact persistence.
- Environment build/publish validation hooks are implemented (`/build` and `/validate-publish` endpoints).
- Job creation enforces environment readiness (`status=ready` + `freeze_key`) before execution enqueue.
- Assignment publish workflow now enforces rubric approval and code-environment readiness (`ready` + `freeze_key`) before publish.
- `AI_ANALYZING` -> `RETRYING_SHIM` is now implemented with deterministic gating (whitespace-only interface mismatch retries).
- MicroVM adapter boundary now supports runtime modes (`pending`, `pilot_local`, `pilot_docker`) with configurable fallback; full isolated snapshot/vsock runtime execution remains the next backend milestone.
- For `microvm` pilot runtime modes, job creation now requires environment-level policy approval in `spec_json.microvm_policy` (`allow_pilot_runtime=true`, `approved_by`).
- MicroVM adapter now also supports `runtime_bridge` mode for external isolated runtime execution contracts.
- MicroVM adapter now also supports `firecracker_vsock` mode for snapshot/vsock guest-agent execution (requires host Firecracker/KVM prerequisites).
- Runtime mode/bridge readiness can be inspected through `GET /code-eval/runtime/status`.
- Firecracker host readiness can be inspected through `GET /code-eval/runtime/preflight`.
- An optional compose-hosted reference bridge service is available for local contract validation (`runtime-bridge` on port `8099`).
- The reference bridge can run either `local_reference` execution or `microvm_transport` forwarding mode behind the same `/execute` contract.

## 5) Profile strategy recommendation

- Provide predefined official environment profiles (e.g., `python-basic`, `cpp17`, `java17`).
- Also allow custom profiles, but require successful freeze/build validation before assignment publish.

## 6) Regrade policy

- Default: process only new submissions after rubric/test/environment changes.
- Historical submissions are reprocessed only when instructor explicitly requests regrade.
