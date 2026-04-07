# Logs and Manual Artifacts

This folder stores runtime evidence and temporary/manual payload artifacts generated during validation.

## Structure

- `manual_scenarios_raw_2026-04-06.txt`
  - Consolidated raw output from multi-scenario manual API runs.

- `manual_artifacts/`
  - Input payloads and ID snapshots used for manual E2E and troubleshooting.
  - Files are kept for reproducibility and postmortem reference.

## Notes

- Artifacts in this folder are not production source code.
- Keep new ad-hoc manual JSON payloads here instead of repository root.
