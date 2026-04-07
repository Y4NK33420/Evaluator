#!/usr/bin/env bash
set -euo pipefail

# One-command Firecracker smoke runner.
# - Ensures snapshot artifacts exist (or refreshes them when requested).
# - Runs the full API-level e2e validation script.

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"

SNAPSHOT_VMSTATE="${SNAPSHOT_VMSTATE:-${ROOT_DIR}/microvm/snapshots/python311.vmstate}"
SNAPSHOT_MEM="${SNAPSHOT_MEM:-${ROOT_DIR}/microvm/snapshots/python311.mem}"
FORCE_REFRESH_SNAPSHOT="${FORCE_REFRESH_SNAPSHOT:-false}"
SKIP_SNAPSHOT_PROBE="${SKIP_SNAPSHOT_PROBE:-false}"

is_true() {
  case "${1,,}" in
    1|true|yes|on) return 0 ;;
    *) return 1 ;;
  esac
}

need_snapshot=false
if is_true "${FORCE_REFRESH_SNAPSHOT}"; then
  need_snapshot=true
elif [[ ! -f "${SNAPSHOT_VMSTATE}" || ! -f "${SNAPSHOT_MEM}" ]]; then
  need_snapshot=true
fi

if [[ "${need_snapshot}" == "true" ]]; then
  echo "[firecracker-smoke] creating snapshot artifacts..."
  SKIP_GUEST_PROBE="${SKIP_SNAPSHOT_PROBE}" "${SCRIPT_DIR}/create_snapshot_with_guest_agent.sh"
else
  echo "[firecracker-smoke] reusing existing snapshot artifacts."
fi

echo "[firecracker-smoke] running end-to-end API validation..."
"${SCRIPT_DIR}/run_linux_firecracker_e2e.sh"
