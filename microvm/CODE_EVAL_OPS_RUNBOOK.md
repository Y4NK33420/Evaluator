# Code Eval Ops Runbook

This runbook covers startup checks, common failure signatures, and recovery actions for code-eval runtime paths.

## 1) Startup order

1. Start core stack:

```powershell
docker compose up -d
```

2. Verify service health:

```powershell
docker compose ps
```

3. Verify runtime mode:

```powershell
curl.exe -sS http://localhost:8080/api/v1/code-eval/runtime/status
```

## 2) Windows baseline policy

- Keep default backend mode on Windows.
- Do not force firecracker_vsock on Docker Desktop hosts.
- Use Firecracker validation only on Linux/KVM hosts.

## 3) Common failure signatures and meaning

1. Static analysis blocked execution due to forbidden patterns.
- Meaning: Stage-1 static gate rejected unsafe source before execution.
- Action: Review attempt_artifacts.violations and update code/test fixture accordingly.

2. runtime_unavailable
- Meaning: Required compiler/runtime tool not available for selected language.
- Action: Install required toolchain or switch to docker backend image with toolchain preinstalled.

3. timeout
- Meaning: testcase exceeded quota timeout.
- Action: inspect algorithm complexity and input size, or adjust timeout policy if intentional.

4. snapshot checksum mismatch
- Meaning: bound snapshot artifact hashes do not match files on disk.
- Action: rebuild snapshots, republish env version, and verify checksum metadata integrity.

5. kvm_unavailable or firecracker_binary_missing
- Meaning: host does not meet Firecracker prerequisites.
- Action: run Linux/KVM preflight and move validation to Linux staging.

## 4) Recovery commands

1. Restore default backend/worker runtime after experiments:

```powershell
docker compose up -d --force-recreate backend worker-code-eval
```

2. Re-run API smoke checks:

```powershell
./logs/validate_api_static_gate.ps1
./logs/validate_env_build_api.ps1
```

3. Re-run focused regression tests:

```powershell
Set-Location d:/dev/DEP/backend
d:/dev/DEP/.venv/Scripts/python.exe -m pytest tests/code_eval -q
```

## 5) Linux/KVM bring-up checks

Run on Linux host:

```bash
./microvm/scripts/linux_host_preflight.sh
./microvm/scripts/firecracker_smoke.sh
```

If preflight fails, resolve host prerequisites before enabling microVM mode.
