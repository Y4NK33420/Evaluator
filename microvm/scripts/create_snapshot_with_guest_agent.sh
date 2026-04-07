#!/usr/bin/env bash
set -euo pipefail

# Creates Firecracker full snapshot artifacts after verifying guest-agent response over vsock.
# Host requirements: Linux + /dev/kvm + firecracker binary + guest rootfs that auto-starts agent.

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"

FIRECRACKER_BIN="${FIRECRACKER_BIN:-/usr/local/bin/firecracker}"
KERNEL_IMAGE="${KERNEL_IMAGE:-${ROOT_DIR}/microvm/assets/vmlinux.bin}"
ROOTFS_IMAGE="${ROOTFS_IMAGE:-${ROOT_DIR}/microvm/assets/python311-agent.rootfs.ext4}"
SNAPSHOT_DIR="${SNAPSHOT_DIR:-${ROOT_DIR}/microvm/snapshots}"
SNAPSHOT_NAME="${SNAPSHOT_NAME:-python311}"
VCPU_COUNT="${VCPU_COUNT:-2}"
MEMORY_MIB="${MEMORY_MIB:-1024}"
GUEST_CID="${GUEST_CID:-3}"
VSOCK_PORT="${VSOCK_PORT:-7000}"
BOOT_WAIT_SECONDS="${BOOT_WAIT_SECONDS:-12}"
SKIP_GUEST_PROBE="${SKIP_GUEST_PROBE:-false}"
ROOTFS_READ_ONLY="${ROOTFS_READ_ONLY:-true}"

API_SOCK="/tmp/firecracker-snap-${SNAPSHOT_NAME}.sock"
VSOCK_UDS="/tmp/firecracker-snap-${SNAPSHOT_NAME}.vsock"
SNAP_VMSTATE="${SNAPSHOT_DIR}/${SNAPSHOT_NAME}.vmstate"
SNAP_MEM="${SNAPSHOT_DIR}/${SNAPSHOT_NAME}.mem"
PAYLOAD_JSON="/tmp/firecracker-guest-probe-${SNAPSHOT_NAME}.json"
FC_PID=""

cleanup() {
  set +e
  if [[ -n "${FC_PID}" ]] && kill -0 "${FC_PID}" >/dev/null 2>&1; then
    kill "${FC_PID}" >/dev/null 2>&1 || true
    wait "${FC_PID}" >/dev/null 2>&1 || true
  fi
  rm -f "${API_SOCK}" "${VSOCK_UDS}" "${PAYLOAD_JSON}"
}
trap cleanup EXIT

require_file() {
  local p="$1"
  local name="$2"
  if [[ ! -f "${p}" ]]; then
    echo "ERROR: ${name} not found: ${p}" >&2
    exit 1
  fi
}

wait_for_socket() {
  local sock="$1"
  local timeout="$2"
  local end=$((SECONDS + timeout))
  while [[ ${SECONDS} -lt ${end} ]]; do
    [[ -S "${sock}" ]] && return 0
    sleep 0.1
  done
  echo "ERROR: timed out waiting for socket ${sock}" >&2
  exit 1
}

is_true() {
  case "${1,,}" in
    1|true|yes|on) return 0 ;;
    *) return 1 ;;
  esac
}

fc_req() {
  local method="$1"
  local path="$2"
  local body="${3:-}"
  local tmp_body
  tmp_body="$(mktemp)"

  local code
  if [[ -n "${body}" ]]; then
    code="$(curl -sS --unix-socket "${API_SOCK}" -X "${method}" "http://localhost${path}" \
      -H 'Content-Type: application/json' \
      --data "${body}" \
      -o "${tmp_body}" -w '%{http_code}')"
  else
    code="$(curl -sS --unix-socket "${API_SOCK}" -X "${method}" "http://localhost${path}" \
      -H 'Content-Type: application/json' \
      -o "${tmp_body}" -w '%{http_code}')"
  fi

  if [[ ! "${code}" =~ ^2 ]]; then
    echo "ERROR: Firecracker API ${method} ${path} failed with HTTP ${code}" >&2
    cat "${tmp_body}" >&2 || true
    rm -f "${tmp_body}"
    exit 1
  fi

  rm -f "${tmp_body}"
}

if [[ ! -x "${FIRECRACKER_BIN}" ]]; then
  echo "ERROR: firecracker binary is missing or not executable: ${FIRECRACKER_BIN}" >&2
  exit 1
fi

if [[ ! -e /dev/kvm ]]; then
  echo "ERROR: /dev/kvm is not available on this host" >&2
  exit 1
fi

require_file "${KERNEL_IMAGE}" "kernel image"
require_file "${ROOTFS_IMAGE}" "rootfs image"

mkdir -p "${SNAPSHOT_DIR}"
rm -f "${SNAP_VMSTATE}" "${SNAP_MEM}" "${API_SOCK}" "${VSOCK_UDS}"

"${FIRECRACKER_BIN}" --api-sock "${API_SOCK}" >/tmp/firecracker-snapshot-create.log 2>&1 &
FC_PID="$!"
wait_for_socket "${API_SOCK}" 8

fc_req PUT /machine-config "{\"vcpu_count\": ${VCPU_COUNT}, \"mem_size_mib\": ${MEMORY_MIB}, \"smt\": false}"
fc_req PUT /boot-source "{\"kernel_image_path\": \"${KERNEL_IMAGE}\", \"boot_args\": \"console=ttyS0 reboot=k panic=1 pci=off root=/dev/vda rw\"}"
fc_req PUT /drives/rootfs "{\"drive_id\":\"rootfs\",\"path_on_host\":\"${ROOTFS_IMAGE}\",\"is_root_device\":true,\"is_read_only\":${ROOTFS_READ_ONLY}}"
fc_req PUT /vsock "{\"vsock_id\":\"vsock0\",\"guest_cid\":${GUEST_CID},\"uds_path\":\"${VSOCK_UDS}\"}"
fc_req PUT /actions "{\"action_type\":\"InstanceStart\"}"

sleep "${BOOT_WAIT_SECONDS}"

if is_true "${SKIP_GUEST_PROBE}"; then
  echo "Skipping guest probe because SKIP_GUEST_PROBE=${SKIP_GUEST_PROBE}"
else
  cat >"${PAYLOAD_JSON}" <<'JSON'
{
  "protocol_version": "v1",
  "stage": "EXECUTING_RAW",
  "comparison_mode": "strict",
  "shim_used": false,
  "shim_source": null,
  "request": {
    "assignment_id": "snapshot-probe",
    "submission_id": "snapshot-probe",
    "language": "python",
    "entrypoint": "main.py",
    "source_files": {
      "main.py": "print('ok')"
    },
    "testcases": [
      {
        "testcase_id": "probe",
        "weight": 1.0,
        "input_mode": "stdin",
        "stdin": "",
        "expected_stdout": "ok",
        "expected_stderr": "",
        "expected_exit_code": 0,
        "files": {}
      }
    ],
    "environment": {
      "mode": "manifest",
      "runtime": "python-3.11"
    },
    "quota": {
      "timeout_seconds": 5.0,
      "memory_mb": 256,
      "max_output_kb": 256,
      "network_enabled": false
    }
  }
}
JSON

  python3 "${SCRIPT_DIR}/vsock_frame_client.py" --uds-path "${VSOCK_UDS}" --port "${VSOCK_PORT}" --payload-file "${PAYLOAD_JSON}" >/tmp/firecracker-guest-probe-response.json
fi

fc_req PATCH /vm "{\"state\":\"Paused\"}"
fc_req PUT /snapshot/create "{\"snapshot_type\":\"Full\",\"snapshot_path\":\"${SNAP_VMSTATE}\",\"mem_file_path\":\"${SNAP_MEM}\"}"

echo "Snapshot created successfully:"
echo "  vmstate: ${SNAP_VMSTATE}"
echo "  mem:     ${SNAP_MEM}"
if is_true "${SKIP_GUEST_PROBE}"; then
  echo "Guest probe was skipped."
else
  echo "Guest probe response saved to /tmp/firecracker-guest-probe-response.json"
fi
