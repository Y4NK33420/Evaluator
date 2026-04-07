#!/usr/bin/env bash
set -euo pipefail

# Installs the guest-agent into an already mounted Linux rootfs directory.
# Usage:
#   ./install_guest_agent_in_rootfs_mount.sh /path/to/mounted/rootfs

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"

ROOTFS_MOUNT="${1:-}"
if [[ -z "${ROOTFS_MOUNT}" ]]; then
  echo "Usage: $0 /path/to/mounted/rootfs" >&2
  exit 1
fi

if [[ ! -d "${ROOTFS_MOUNT}" ]]; then
  echo "ERROR: rootfs mount directory does not exist: ${ROOTFS_MOUNT}" >&2
  exit 1
fi

if [[ ! -d "${ROOTFS_MOUNT}/etc/systemd/system" ]]; then
  echo "ERROR: ${ROOTFS_MOUNT} does not appear to be a systemd rootfs" >&2
  exit 1
fi

install -d "${ROOTFS_MOUNT}/opt/codeeval"
install -m 0755 "${ROOT_DIR}/microvm_guest_agent/agent.py" "${ROOTFS_MOUNT}/opt/codeeval/agent.py"
install -d "${ROOTFS_MOUNT}/etc/systemd/system"
install -m 0644 "${ROOT_DIR}/microvm_guest_agent/codeeval-guest-agent.service" "${ROOTFS_MOUNT}/etc/systemd/system/codeeval-guest-agent.service"
install -d "${ROOTFS_MOUNT}/etc/systemd/system/multi-user.target.wants"
ln -sf "/etc/systemd/system/codeeval-guest-agent.service" "${ROOTFS_MOUNT}/etc/systemd/system/multi-user.target.wants/codeeval-guest-agent.service"

echo "Installed guest-agent into ${ROOTFS_MOUNT}"
