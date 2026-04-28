# Firecracker Guest Agent (Reference)

This directory contains a reference guest-agent for code-eval microVM execution.

## Purpose

- Receive code-eval execution requests over vsock.
- Execute testcases inside the guest VM (Python, C, C++, Java).
- Return deterministic JSON result payload to the host.

## Protocol

Transport uses length-prefixed JSON frames:

1. Host sends 4-byte big-endian frame length + JSON payload.
2. Guest returns same frame format with execution response.

Host payload shape (simplified):

```json
{
  "protocol_version": "v1",
  "stage": "EXECUTING_RAW",
  "comparison_mode": "strict",
  "shim_used": false,
  "shim_source": null,
  "request": { "...CodeEvalJobRequest fields...": true }
}
```

Guest response shape:

```json
{
  "passed": true,
  "exit_code": 0,
  "stdout": "...",
  "stderr": "",
  "score": 2.0,
  "artifacts": { "engine": "firecracker_guest_agent" }
}
```

## Run in guest VM

```bash
python /opt/codeeval/agent.py
```

Environment variables:

- `CODE_EVAL_GUEST_AGENT_PORT` (default `7000`)
- `CODE_EVAL_GUEST_AGENT_PYTHON_EXEC` (optional explicit interpreter path)
- `CODE_EVAL_GUEST_AGENT_STRICT_RUNTIME` (default `false`; when `true`, fail if requested runtime major version is unavailable)
- `CODE_EVAL_GUEST_AGENT_ALLOW_DYNAMIC_PIP` (default `false`; when `true`, install request-level pip deps into isolated temp dir)

## Python Runtime Selection

The agent resolves interpreter in this order:

1. `CODE_EVAL_GUEST_AGENT_PYTHON_EXEC` (if set and executable)
2. `request.environment.runtime` hint:
  - `python-3.x` -> prefers `python3`
  - `python-2.x` -> prefers `python2.7`
3. fallback auto-detection (`python3`, then `python2.7`, then `sys.executable`)

When strict runtime is enabled and `request.environment.runtime` asks for `python-3.x`, the agent will fail if Python 3 is not present in the guest image.

If requested runtime is unavailable in guest image, execution fails with an explicit error.

## Dependency Installation

Python dependencies can be provided via `request.environment.manifest` keys:

- `pip`
- `pip_packages`
- `requirements`
- `requirements_txt`

Accepted formats:

- comma-separated string (`numpy==1.26,pydantic==2.7.1`)
- newline-separated string
- JSON array string (`["numpy==1.26", "pydantic==2.7.1"]`)

Dependencies are installed into an isolated per-request target directory via:

`<python_exec> -m pip install --target <tmp-dir> ...`

That directory is injected through `PYTHONPATH` for testcase execution.

For strict isolation, dynamic installs are disabled by default and environments should be pre-baked into snapshots.
