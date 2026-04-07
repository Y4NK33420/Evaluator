#!/usr/bin/env bash
set -euo pipefail

# Mounts an ext4 rootfs image via loop device, installs guest-agent files,
# then unmounts. Requires sudo/root permissions.

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOTFS_IMAGE="${1:-}"
MOUNT_DIR="${2:-/tmp/codeeval-rootfs-mount}"

if [[ -z "${ROOTFS_IMAGE}" ]]; then
  echo "Usage: $0 /path/to/rootfs.ext4 [mount_dir]" >&2
  exit 1
fi

if [[ ! -f "${ROOTFS_IMAGE}" ]]; then
  echo "ERROR: rootfs image not found: ${ROOTFS_IMAGE}" >&2
  exit 1
fi

cleanup() {
  set +e
  if mountpoint -q "${MOUNT_DIR}"; then
    sudo umount "${MOUNT_DIR}" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

sudo mkdir -p "${MOUNT_DIR}"
sudo mount -o loop "${ROOTFS_IMAGE}" "${MOUNT_DIR}"

"${SCRIPT_DIR}/install_guest_agent_in_rootfs_mount.sh" "${MOUNT_DIR}"

sync
sudo umount "${MOUNT_DIR}"

echo "Guest-agent installed into rootfs image: ${ROOTFS_IMAGE}"
