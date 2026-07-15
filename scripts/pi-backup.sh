#!/usr/bin/env bash
# pi-backup.sh — snapshot the jcmcp k3s data volume to the USB backup drive
# on the Pi (Node1). Lives in the repo for review; installed on the Pi at
# /usr/local/bin/jcmcp-backup.sh and run nightly by jcmcp-backup.timer
# (see scripts/pi-deploy.sh backup-setup).
#
# Design: rsync everything except live SQLite files, then take a consistent
# per-DB copy via sqlite3's online .backup (safe mid-write). Timestamped
# snapshot dirs under /mnt/backup/jcmcp, newest KEEP retained.
set -euo pipefail

DEST_ROOT=/mnt/backup/jcmcp
KEEP=7
STAMP=$(date +%Y%m%d-%H%M%S)
DEST="${DEST_ROOT}/${STAMP}"

# fstab mounts the drive nofail — never write to the bare mountpoint dir.
mountpoint -q /mnt/backup || { echo "backup drive not mounted"; exit 1; }

# The app's PVC as provisioned by k3s local-path.
SRC=$(ls -d /var/lib/rancher/k3s/storage/pvc-*_jcmcp-pi_jcmcp-pi-data 2>/dev/null | head -1)
[ -n "${SRC}" ] || { echo "jcmcp-pi data PVC not found"; exit 1; }

mkdir -p "${DEST}"

rsync -a --exclude='*.db' --exclude='*.db-wal' --exclude='*.db-shm' \
  "${SRC}/" "${DEST}/data/"

find "${SRC}" -name '*.db' | while read -r db; do
  rel="${db#"${SRC}"/}"
  mkdir -p "${DEST}/data/$(dirname "${rel}")"
  sqlite3 "${db}" ".backup '${DEST}/data/${rel}'"
done

# Node config worth having when rebuilding after an SD-card death.
mkdir -p "${DEST}/node"
cp /boot/firmware/cmdline.txt "${DEST}/node/" 2>/dev/null || true
cp /etc/fstab "${DEST}/node/" 2>/dev/null || true

# Retention: drop everything but the newest ${KEEP} snapshots.
ls -1d "${DEST_ROOT}"/*/ 2>/dev/null | sort | head -n -"${KEEP}" | xargs -r rm -rf

echo "backup OK: ${DEST} ($(du -sh "${DEST}" | cut -f1))"
