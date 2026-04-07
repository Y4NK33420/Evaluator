# Linux Deployment Guide for Firecracker Runtime

This guide keeps development stable on Windows while preserving a clean path to deploy Firecracker on Linux later.

## Current policy

- Windows development stays on default backend mode.
- Firecracker microVM runtime is enabled only on Linux hosts with KVM.
- No code rewrites are required for Linux deployment; this is an environment and deployment switch.

## What to keep on Windows

1. Keep default runtime settings in your local environment.
2. Use normal stack startup:

```powershell
docker compose up -d
```

3. Use runtime status endpoint to verify backend mode:

```powershell
curl.exe -sS http://localhost:8080/api/v1/code-eval/runtime/status
```

Expected on Windows: execution backend is local or docker, not firecracker_vsock.

## Linux deployment checklist

Run these steps on a Linux machine with hardware virtualization enabled.

1. Verify host prerequisites:

```bash
./microvm/scripts/linux_host_preflight.sh
```

2. Prepare guest rootfs with the agent:

```bash
./microvm/scripts/mount_rootfs_and_install_guest_agent.sh ./microvm/assets/python311-agent.rootfs.ext4
```

3. Create snapshot artifacts:

```bash
./microvm/scripts/create_snapshot_with_guest_agent.sh
```

4. Start backend and worker in microVM mode:

```bash
docker compose -f docker-compose.yml -f docker-compose.microvm.yml up -d backend worker-code-eval
```

5. Verify runtime readiness:

```bash
curl -s http://localhost:8080/api/v1/code-eval/runtime/status
curl -s http://localhost:8080/api/v1/code-eval/runtime/preflight
```

Expected values include:
- execution backend is microvm
- runtime mode is firecracker_vsock
- preflight ready is true

6. Run end-to-end validation:

```bash
./microvm/scripts/firecracker_smoke.sh
```

## Required Linux-side changes

No application code changes are required. Only host and deployment settings must be present:

1. Linux host exposes /dev/kvm.
2. Firecracker binary exists in microVM image (handled by backend/Dockerfile.microvm).
3. Snapshot files exist and are mounted at expected paths.
4. Backend and worker run with docker-compose.microvm.yml override.

## Rollback procedure

If you need to disable microVM mode quickly on Linux:

```bash
docker compose up -d --force-recreate backend worker-code-eval
```

This restores service defaults from docker-compose.yml.

## Notes

- Keep fallback disabled when validating true Firecracker behavior.
- Keep network isolation enabled for microVM jobs.
- Prefer running Firecracker checks in Linux staging or CI, even if daily development stays on Windows.
