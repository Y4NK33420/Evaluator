# MicroVM Runtime (Firecracker + VSOCK)

This folder contains deployment assets for real code-eval execution on Linux/KVM hosts.

## What is included

- `docker-compose.microvm.yml`: compose override that enables `firecracker_vsock` mode.
- `backend/Dockerfile.microvm`: backend/worker image with Firecracker binary installed.
- `scripts/create_snapshot_with_guest_agent.sh`: creates full snapshot after guest-agent probe.
- `scripts/firecracker_smoke.ps1`: Windows PowerShell one-command smoke runner.
- `scripts/mount_rootfs_and_install_guest_agent.sh`: mounts ext4 rootfs image and installs guest-agent + systemd unit.
- `scripts/firecracker_smoke.sh`: one-command snapshot+e2e smoke runner.
- `scripts/run_linux_firecracker_e2e.sh`: full Linux/KVM e2e validation runner.
- `assets/`: kernel/rootfs boot assets used to create the initial snapshot.
- `snapshots/`: expected snapshot artifact location.
- `runtime/`: runtime scratch area (API sockets, run dirs).
- `../microvm_guest_agent/`: reference in-guest vsock agent implementation.

## Host prerequisites

- Linux host with KVM support (`/dev/kvm` present and usable).
- Docker Engine on Linux (not Docker Desktop VM-on-VM abstraction).
- Firecracker-compatible snapshot artifacts:
  - `/opt/microvm/snapshots/python311.vmstate`
  - `/opt/microvm/snapshots/python311.mem`
- Guest image corresponding to snapshot must run the guest-agent at boot:
  - `python /opt/codeeval/agent.py`

Quick preflight check (recommended before bring-up):

```bash
./microvm/scripts/linux_host_preflight.sh
```

If you are developing on Windows and deploying Firecracker later on Linux, follow:
- `microvm/LINUX_DEPLOYMENT_GUIDE.md`

## Bring-up (Linux host)

### Step 1: Prepare guest rootfs with agent

Install agent into your bootable ext4 rootfs image:

```bash
./microvm/scripts/mount_rootfs_and_install_guest_agent.sh ./microvm/assets/python311-agent.rootfs.ext4
```

### Step 2: Create snapshot artifacts

Create a full snapshot and verify in-guest agent over vsock before freezing:

```bash
./microvm/scripts/create_snapshot_with_guest_agent.sh
```

This produces:
- `microvm/snapshots/python311.vmstate`
- `microvm/snapshots/python311.mem`

### Step 3: Run microvm stack

```bash
docker compose -f docker-compose.yml -f docker-compose.microvm.yml up -d backend worker-code-eval
```

Then check:

```bash
curl -s http://localhost:8080/api/v1/code-eval/runtime/status | jq
curl -s http://localhost:8080/api/v1/code-eval/runtime/preflight | jq
```

Expected for ready host:

- `execution_backend = microvm`
- `microvm.runtime_mode = firecracker_vsock`
- `microvm.firecracker_preflight_ready = true`
- `runtime/preflight.firecracker.ready = true`

### Step 4: Run full e2e smoke

Single command (recommended):

```bash
./microvm/scripts/firecracker_smoke.sh
```

Windows PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\microvm\scripts\firecracker_smoke.ps1
```

Options:

- `FORCE_REFRESH_SNAPSHOT=true` to always recreate snapshot artifacts.
- `SKIP_SNAPSHOT_PROBE=true` to skip guest probe during snapshot creation.

Manual e2e runner (uses existing snapshots):

```bash
./microvm/scripts/run_linux_firecracker_e2e.sh
```

This script creates assignment/env/submission/job and waits for terminal state.

## Notes

- On non-KVM dev hosts, runtime will fail fast with deterministic reasons such as:
  - `firecracker_binary_missing`
  - `kvm_unavailable`
  - `snapshot_vmstate_missing`
- Keep fallback disabled (`CODE_EVAL_MICROVM_ALLOW_FALLBACK=false`) when validating real Firecracker path.
- Runtime now enforces network isolation when `CODE_EVAL_MICROVM_FORCE_NO_NETWORK=true`.
- Firecracker runs use a serial lock file (`CODE_EVAL_MICROVM_SERIAL_LOCK_FILE`) to avoid shared vsock fallback collisions on legacy API paths.

## Windows now, Linux later

- Keep default compose mode on Windows (local or docker backend).
- Do not force `firecracker_vsock` on Windows Docker Desktop hosts.
- Validate Firecracker runtime only on Linux/KVM hosts using the Linux preflight script and e2e runners above.
