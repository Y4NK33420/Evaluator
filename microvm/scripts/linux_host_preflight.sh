#!/usr/bin/env bash
set -euo pipefail

# Linux host readiness check for Firecracker runtime deployment.

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
SNAPSHOT_VMSTATE="${SNAPSHOT_VMSTATE:-${ROOT_DIR}/microvm/snapshots/python311.vmstate}"
SNAPSHOT_MEM="${SNAPSHOT_MEM:-${ROOT_DIR}/microvm/snapshots/python311.mem}"
FIRECRACKER_BIN="${FIRECRACKER_BIN:-/usr/local/bin/firecracker}"

FAILURES=0

ok() {
  printf "[OK] %s\n" "$1"
}

warn() {
  printf "[WARN] %s\n" "$1"
}

fail() {
  printf "[FAIL] %s\n" "$1"
  FAILURES=$((FAILURES + 1))
}

check_cmd() {
  local name="$1"
  if command -v "${name}" >/dev/null 2>&1; then
    ok "command available: ${name}"
  else
    fail "command missing: ${name}"
  fi
}

if [[ "$(uname -s)" != "Linux" ]]; then
  fail "host OS is not Linux"
else
  ok "host OS is Linux"
fi

check_cmd docker
check_cmd curl

if docker compose version >/dev/null 2>&1; then
  ok "docker compose plugin is available"
else
  fail "docker compose plugin is not available"
fi

if [[ -c /dev/kvm ]]; then
  ok "/dev/kvm exists"
  if [[ -r /dev/kvm && -w /dev/kvm ]]; then
    ok "/dev/kvm is readable and writable"
  else
    warn "/dev/kvm exists but current user may not have rw access"
    warn "consider adding user to kvm group and re-login"
  fi
else
  fail "/dev/kvm is missing"
fi

if [[ -f "${FIRECRACKER_BIN}" ]]; then
  ok "firecracker binary found at ${FIRECRACKER_BIN}"
else
  warn "firecracker binary not found at ${FIRECRACKER_BIN}"
  warn "this can still pass if your runtime image installs firecracker (backend/Dockerfile.microvm)"
fi

if [[ -f "${SNAPSHOT_VMSTATE}" ]]; then
  ok "snapshot vmstate exists: ${SNAPSHOT_VMSTATE}"
else
  fail "snapshot vmstate missing: ${SNAPSHOT_VMSTATE}"
fi

if [[ -f "${SNAPSHOT_MEM}" ]]; then
  ok "snapshot memory exists: ${SNAPSHOT_MEM}"
else
  fail "snapshot memory missing: ${SNAPSHOT_MEM}"
fi

if [[ "${FAILURES}" -gt 0 ]]; then
  printf "\nPreflight failed with %s blocking issue(s).\n" "${FAILURES}"
  exit 1
fi

printf "\nPreflight passed. Linux host appears ready for Firecracker deployment.\n"
