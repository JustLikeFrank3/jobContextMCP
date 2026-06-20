#!/usr/bin/env bash
# ── sync_data_from_azure.sh ───────────────────────────────────────────────────
# One-way pull of a user's data from Azure Blob Storage into a local data/
# directory.  Primary target is the iCloud production workspace; from there
# the existing sync_data_from_production.sh can cascade into this dev workspace.
#
# Blob layout (container: workspace):
#   users/{OID}/*.json
#   users/{OID}/jobcontextmcp.db
#   users/{OID}/workspace/...
#
# Local layout (same as production iCloud workspace):
#   data/*.json
#   data/jobcontextmcp.db
#   data/workspace/... (NOT synced by default — resume materials only)
#
# Direction: Azure Blob → local destination.  Never the reverse.
#
# ─────────────────────────────────────────────────────────────────────────────
# Usage:
#   ./scripts/sync_data_from_azure.sh [--dry-run | --quick | --full] [options]
#
#   --dry-run     List blobs and show what would change, no download (default)
#   --quick       Download with no pre-sync backup (fast)
#   --full        Download with a timestamped backup of current dest (safe)
#
# Options:
#   --oid OID              Override OID (default: ENTRA_OWNER_OID from .env)
#   --dest PATH            Override destination (default: AZURE_SYNC_DEST from
#                          .env, or the configured iCloud production data/ path)
#   --account NAME         Override storage account (default: from .env or
#                          jcmcp-config configmap)
#   --container NAME       Override container (default: workspace)
#   --include-workspace    Also sync users/{OID}/workspace/ tree (resume files)
#   --yes                  Skip confirmation prompt
#   --help
#
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

# ── Defaults ─────────────────────────────────────────────────────────────────
MODE="dry-run"
OID_OVERRIDE=""
DEST_OVERRIDE=""
ACCOUNT_OVERRIDE=""
CONTAINER="workspace"
INCLUDE_WORKSPACE=false
ASSUME_YES=false

# ── Parse flags ──────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run)           MODE="dry-run" ;;
        --quick)             MODE="quick" ;;
        --full)              MODE="full" ;;
        --oid)               OID_OVERRIDE="$2"; shift ;;
        --dest)              DEST_OVERRIDE="$2"; shift ;;
        --account)           ACCOUNT_OVERRIDE="$2"; shift ;;
        --container)         CONTAINER="$2"; shift ;;
        --include-workspace) INCLUDE_WORKSPACE=true ;;
        --yes|-y)            ASSUME_YES=true ;;
        --help|-h)
            sed -n '17,42p' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *)
            echo "Unknown flag: $1" >&2
            echo "Run with --help for usage." >&2
            exit 2
            ;;
    esac
    shift
done

# ── Resolve paths & config ───────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKUPS_DIR="$REPO_ROOT/backups"
RETENTION="${BACKUP_RETENTION:-10}"

# Load .env for ENTRA_OWNER_OID, AZURE_SYNC_DEST, AZURE_STORAGE_ACCOUNT, etc.
if [[ -f "$REPO_ROOT/.env" ]]; then
    set -a
    # shellcheck source=/dev/null
    source "$REPO_ROOT/.env"
    set +a
fi

# OID — required
OID="${OID_OVERRIDE:-${ENTRA_OWNER_OID:-}}"
if [[ -z "$OID" ]]; then
    echo "❌ OID not set. Pass --oid or set ENTRA_OWNER_OID in .env" >&2
    exit 1
fi

# Storage account
ACCOUNT="${ACCOUNT_OVERRIDE:-${AZURE_STORAGE_ACCOUNT:-jcmcpstore}}"

# Destination — default to the iCloud production data/ folder
DEFAULT_ICLOUD_DEST="$HOME/Library/Mobile Documents/com~apple~CloudDocs/Projects/jobContextMCP-SelfSetup/jobContextMCP/data"
DEST="${DEST_OVERRIDE:-${AZURE_SYNC_DEST:-$DEFAULT_ICLOUD_DEST}}"

# Resume/workspace destination — numbered content folders inside the iCloud workspace
# 01-Current-Optimized/  → resume txt files
# 02-Cover-Letters/      → cover letter txt files
# 03-Resume-PDFs/        → resume PDFs
# 09-Cover-Letter-PDFs/  → cover letter PDFs
DEFAULT_RESUME_DEST="$HOME/Library/Mobile Documents/com~apple~CloudDocs/Projects/jobContextMCP-SelfSetup/jobContextMCP/workspace/resumes"
RESUME_DEST="${AZURE_RESUME_DEST:-$DEFAULT_RESUME_DEST}"

BLOB_PREFIX="users/${OID}"

# ── Sanity checks ────────────────────────────────────────────────────────────
if ! command -v az &>/dev/null; then
    echo "❌ Azure CLI (az) not found. Install from https://aka.ms/installazurecli" >&2
    exit 1
fi

# ── Show the plan ─────────────────────────────────────────────────────────────
echo "☁️  jobContextMCP — Azure Blob → local sync"
echo ""
echo "   Account   : $ACCOUNT"
echo "   Container : $CONTAINER"
echo "   Blob path : ${BLOB_PREFIX}/"
echo "   Dest      : $DEST"
echo "   Mode      : $MODE"
if $INCLUDE_WORKSPACE; then
    echo "   Workspace : included → $RESUME_DEST"
else
    echo "   Workspace : excluded (pass --include-workspace to include resume/cover letter files)"
fi
echo ""

# ── DRY RUN ──────────────────────────────────────────────────────────────────
if [[ "$MODE" == "dry-run" ]]; then
    echo "🔍 DRY RUN — data-layer blobs that would be synced to $DEST"
    echo "   (workspace content folders excluded; db/ flattened to root)"
    echo ""
    az storage blob list \
        --account-name "$ACCOUNT" \
        --container-name "$CONTAINER" \
        --prefix "${BLOB_PREFIX}/" \
        --auth-mode login \
        --query "[?!(starts_with(name, '${BLOB_PREFIX}/01-Current-Optimized/') || starts_with(name, '${BLOB_PREFIX}/02-Cover-Letters/') || starts_with(name, '${BLOB_PREFIX}/03-Resume-PDFs/') || starts_with(name, '${BLOB_PREFIX}/06-Reference-Materials/') || starts_with(name, '${BLOB_PREFIX}/07-Job-Assessments/') || starts_with(name, '${BLOB_PREFIX}/08-Interview-Prep-Docs/') || starts_with(name, '${BLOB_PREFIX}/09-Cover-Letter-PDFs/') || starts_with(name, '${BLOB_PREFIX}/frank-resume-latex/') || starts_with(name, '${BLOB_PREFIX}/leetcode/') || starts_with(name, '${BLOB_PREFIX}/workspace/'))].{name:name, size:properties.contentLength, modified:properties.lastModified}" \
        --output table 2>&1 || {
            echo ""
            echo "⚠️  Could not list blobs. Check your az login / permissions."
            echo "   Try: az login  (or az account show to verify active session)"
            exit 1
        }
    if $INCLUDE_WORKSPACE; then
        echo ""
        echo "🔍 WORKSPACE — resume/cover letter blobs that would sync to $RESUME_DEST"
        echo ""
        az storage blob list \
            --account-name "$ACCOUNT" \
            --container-name "$CONTAINER" \
            --prefix "${BLOB_PREFIX}/" \
            --auth-mode login \
            --query "[?starts_with(name, '${BLOB_PREFIX}/01-Current-Optimized/') || starts_with(name, '${BLOB_PREFIX}/02-Cover-Letters/') || starts_with(name, '${BLOB_PREFIX}/03-Resume-PDFs/') || starts_with(name, '${BLOB_PREFIX}/09-Cover-Letter-PDFs/')].{name:name, size:properties.contentLength, modified:properties.lastModified}" \
            --output table 2>&1 || true
    fi
    echo ""
    echo "✅ Dry run complete. No files downloaded."
    echo "   Run with --quick (fast) or --full (with backup) to download."
    exit 0
fi

# ── Confirmation ─────────────────────────────────────────────────────────────
if ! $ASSUME_YES; then
    read -r -p "Download blobs from ${ACCOUNT}/${CONTAINER}/${BLOB_PREFIX}/ → ${DEST}? [y/N] " reply
    if [[ ! "$reply" =~ ^[Yy]$ ]]; then
        echo "Aborted."
        exit 0
    fi
    echo ""
fi

# ── Backup current dest (full mode only) ─────────────────────────────────────
if [[ "$MODE" == "full" ]]; then
    TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
    mkdir -p "$BACKUPS_DIR"

    # Always back up the data/ folder
    if [[ -d "$DEST" ]]; then
        BACKUP_FILE="$BACKUPS_DIR/data_azure_${TIMESTAMP}.tar.gz"
        echo "📦 Snapshotting data/ → $(basename "$BACKUP_FILE") ..."
        tar -czf "$BACKUP_FILE" -C "$(dirname "$DEST")" "$(basename "$DEST")"
        BACKUP_SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
        echo "   Saved: $BACKUP_FILE ($BACKUP_SIZE)"
        echo ""
    fi

    # Also back up workspace/resumes/ when --include-workspace is set
    if $INCLUDE_WORKSPACE && [[ -d "$RESUME_DEST" ]]; then
        RESUME_BACKUP_FILE="$BACKUPS_DIR/resumes_azure_${TIMESTAMP}.tar.gz"
        echo "📦 Snapshotting workspace/resumes/ → $(basename "$RESUME_BACKUP_FILE") ..."
        tar -czf "$RESUME_BACKUP_FILE" -C "$(dirname "$RESUME_DEST")" "$(basename "$RESUME_DEST")"
        RESUME_BACKUP_SIZE=$(du -h "$RESUME_BACKUP_FILE" | cut -f1)
        echo "   Saved: $RESUME_BACKUP_FILE ($RESUME_BACKUP_SIZE)"
        echo ""
    fi

    # Prune old azure backups (data and resumes separately)
    cd "$BACKUPS_DIR"
    for PATTERN in "data_azure_*.tar.gz" "resumes_azure_*.tar.gz"; do
        # shellcheck disable=SC2012
        OLD=$(ls -1t $PATTERN 2>/dev/null | tail -n +"$((RETENTION + 1))" || true)
        if [[ -n "$OLD" ]]; then
            echo "🧹 Pruning old backups ($PATTERN):"
            echo "$OLD" | while read -r old; do
                echo "   rm $old"
                rm -f "$old"
            done
            echo ""
        fi
    done
    cd - &>/dev/null
fi

# ── Download blobs to temp dir, then rsync into dest ─────────────────────────
# az storage blob download-batch doesn't strip blob path prefixes, so we
# download to a temp dir and rsync from users/{OID}/ into DEST.
TMPDIR="$(mktemp -d)"
trap 'rm -rf "$TMPDIR"' EXIT

echo "⬇️  Downloading blobs..."
echo ""

# Build the pattern — optionally exclude workspace/ subtree
if $INCLUDE_WORKSPACE; then
    PATTERN="${BLOB_PREFIX}/*"
else
    # Download only files directly under users/{OID}/ (no subdirectories).
    # az storage blob download-batch --pattern does fnmatch, so:
    #   "users/{OID}/*"      matches everything including users/{OID}/workspace/foo
    # We use the include-workspace flag to gate this; for the default (no workspace)
    # we still use the wildcard pattern but then only rsync the flat files.
    PATTERN="${BLOB_PREFIX}/*"
fi

az storage blob download-batch \
    --account-name "$ACCOUNT" \
    --source "$CONTAINER" \
    --pattern "$PATTERN" \
    --destination "$TMPDIR" \
    --overwrite true \
    --auth-mode login \
    --output none 2>&1 || {
        echo "❌ Download failed. Check az login and storage permissions." >&2
        exit 1
    }

# Blobs land at $TMPDIR/users/{OID}/...
BLOB_LOCAL_ROOT="$TMPDIR/${BLOB_PREFIX}"

if [[ ! -d "$BLOB_LOCAL_ROOT" ]]; then
    echo "⚠️  No files found under ${BLOB_PREFIX}/ — nothing to sync."
    exit 0
fi

# ── Rsync downloaded files into DEST ─────────────────────────────────────────
# The blob container stores resume materials, job assessments, interview docs,
# etc. under numbered folders (02-Cover-Letters/, 03-Resume-PDFs/, ...) in
# addition to the flat data JSON files and personas/.  We only want the data
# layer here — JSON files, personas/, and the SQLite DB.  Resume/workspace
# materials belong in the Resume 2025 folder, not in data/.
mkdir -p "$DEST"

RSYNC_ARGS=(
    --archive
    --human-readable
    --itemize-changes
    --exclude='.DS_Store'
    # Exclude workspace content folders — not data layer
    --exclude='01-Current-Optimized/'
    --exclude='02-Cover-Letters/'
    --exclude='03-Resume-PDFs/'
    --exclude='06-Reference-Materials/'
    --exclude='07-Job-Assessments/'
    --exclude='08-Interview-Prep-Docs/'
    --exclude='09-Cover-Letter-PDFs/'
    --exclude='frank-resume-latex/'
    --exclude='leetcode/'
    --exclude='workspace/'
    # DB lives in db/ in blob but expected flat in data/ locally
    --exclude='db/'
)

echo "⏬ Merging JSON + personas into $DEST ..."
echo ""

rsync "${RSYNC_ARGS[@]}" "$BLOB_LOCAL_ROOT/" "$DEST/"

# ── Sync workspace content (resumes, cover letters) to RESUME_DEST ──────────
# Only runs when --include-workspace is passed. Syncs numbered content folders
# from blob into the local Resume 2025 folder so new AI-generated files that
# exist in Azure but not locally are pulled down.
if $INCLUDE_WORKSPACE; then
    WORKSPACE_CONTENT_FOLDERS=(
        "01-Current-Optimized"
        "02-Cover-Letters"
        "03-Resume-PDFs"
        "09-Cover-Letter-PDFs"
    )
    echo ""
    echo "⏬ Syncing workspace content → $RESUME_DEST ..."
    echo ""
    for FOLDER in "${WORKSPACE_CONTENT_FOLDERS[@]}"; do
        FOLDER_SRC="$BLOB_LOCAL_ROOT/$FOLDER"
        if [[ -d "$FOLDER_SRC" ]]; then
            FOLDER_DEST="$RESUME_DEST/$FOLDER"
            mkdir -p "$FOLDER_DEST"
            rsync --archive --human-readable --itemize-changes \
                  --exclude='.DS_Store' \
                  "$FOLDER_SRC/" "$FOLDER_DEST/"
        fi
    done
fi

# ── Flatten db/jobcontextmcp.db → $DEST/jobcontextmcp.db ─────────────────────
DB_BLOB_PATH="$BLOB_LOCAL_ROOT/db/jobcontextmcp.db"
if [[ -f "$DB_BLOB_PATH" ]]; then
    echo ""
    echo "⏬ Flattening db/jobcontextmcp.db → $(basename "$DEST")/jobcontextmcp.db ..."
    cp "$DB_BLOB_PATH" "$DEST/jobcontextmcp.db"
    # Copy WAL/SHM if present (consistent snapshot)
    [[ -f "${DB_BLOB_PATH}-wal" ]] && cp "${DB_BLOB_PATH}-wal" "$DEST/jobcontextmcp.db-wal"
    [[ -f "${DB_BLOB_PATH}-shm" ]] && cp "${DB_BLOB_PATH}-shm" "$DEST/jobcontextmcp.db-shm"
fi

echo ""
FILE_COUNT=$(find "$DEST" -type f | wc -l | tr -d ' ')
DEST_SIZE=$(du -sh "$DEST" | cut -f1)
echo "✅ Sync complete. $FILE_COUNT files, $DEST_SIZE total"
echo ""
echo "   Next: run  ./scripts/sync_data_from_production.sh --yes"
echo "   to cascade into this dev workspace."
