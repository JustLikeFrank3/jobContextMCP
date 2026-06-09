#!/usr/bin/env bash
# ── sync_data_from_production.sh ─────────────────────────────────────────────
# One-way sync of data/ from the production iCloud workspace into this dev
# workspace. Does TWO things at once:
#   1. Pulls fresh JSON state so dev/test runs against real-world data
#   2. Creates timestamped backup snapshots on non-cloud storage
#
# Direction is HARD-CODED: production iCloud → this dev workspace. Never the
# reverse. Code changes happen here; data changes happen there. Mixing them
# corrupts job-hunt state.
#
# ─────────────────────────────────────────────────────────────────────────────
# Configure source via DATA_SYNC_SOURCE in .env (or env var). Default:
#   ~/Library/Mobile Documents/com~apple~CloudDocs/Projects/jobContextMCP-SelfSetup/jobContextMCP/data
#
# Usage:
#   ./scripts/sync_data_from_production.sh           # snapshot + sync (prompts)
#   ./scripts/sync_data_from_production.sh --dry-run # show what would change
#   ./scripts/sync_data_from_production.sh --yes     # skip confirmation prompt
#   ./scripts/sync_data_from_production.sh --no-backup  # skip pre-sync snapshot
#
# Backups land in backups/data_YYYYMMDD_HHMMSS.tar.gz.
# Oldest beyond BACKUP_RETENTION (default 10) are pruned automatically.
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

# ── Parse flags ──────────────────────────────────────────────────────────────
DRY_RUN=false
ASSUME_YES=false
SKIP_BACKUP=false

for arg in "$@"; do
    case "$arg" in
        --dry-run)    DRY_RUN=true ;;
        --yes|-y)     ASSUME_YES=true ;;
        --no-backup)  SKIP_BACKUP=true ;;
        --help|-h)
            sed -n '2,22p' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *)
            echo "Unknown flag: $arg" >&2
            echo "Run with --help for usage." >&2
            exit 2
            ;;
    esac
done

# ── Resolve paths ────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Load .env so DATA_SYNC_SOURCE / BACKUP_RETENTION can be configured there
if [[ -f "$REPO_ROOT/.env" ]]; then
    set -a
    # shellcheck source=/dev/null
    source "$REPO_ROOT/.env"
    set +a
fi

DEFAULT_SRC="$HOME/Library/Mobile Documents/com~apple~CloudDocs/Projects/jobContextMCP-SelfSetup/jobContextMCP/data"
SRC="${DATA_SYNC_SOURCE:-$DEFAULT_SRC}"
DEST="$REPO_ROOT/data"
BACKUPS_DIR="$REPO_ROOT/backups"
RETENTION="${BACKUP_RETENTION:-10}"

# ── Sanity checks ────────────────────────────────────────────────────────────
if [[ ! -d "$SRC" ]]; then
    echo "❌ Source directory not found:" >&2
    echo "   $SRC" >&2
    echo "" >&2
    echo "   Set DATA_SYNC_SOURCE in .env to the absolute path of your" >&2
    echo "   production workspace's data/ folder." >&2
    exit 1
fi

if [[ ! -d "$DEST" ]]; then
    echo "❌ Destination directory not found: $DEST" >&2
    echo "   Run from a complete jobContextMCP checkout." >&2
    exit 1
fi

# Resolve real paths to catch symlink-based loops
SRC_REAL="$(cd "$SRC" && pwd -P)"
DEST_REAL="$(cd "$DEST" && pwd -P)"

if [[ "$SRC_REAL" == "$DEST_REAL" ]]; then
    echo "❌ Source and destination resolve to the same directory:" >&2
    echo "   $SRC_REAL" >&2
    echo "   Refusing to sync (would be a no-op or destructive)." >&2
    exit 1
fi

# Reject obviously-empty sources (probable misconfig — would --delete everything)
SRC_FILE_COUNT=$(find "$SRC" -type f -not -name '.DS_Store' | wc -l | tr -d ' ')
if [[ "$SRC_FILE_COUNT" -eq 0 ]]; then
    echo "❌ Source directory contains no files (excluding .DS_Store):" >&2
    echo "   $SRC" >&2
    echo "   Refusing to sync (this would wipe destination)." >&2
    exit 1
fi

# ── Show the plan ────────────────────────────────────────────────────────────
echo "📂 jobContextMCP data sync"
echo ""
echo "   Source  : $SRC"
echo "   Dest    : $DEST"
echo "   Backup  : $([ "$SKIP_BACKUP" = "true" ] && echo "DISABLED" || echo "$BACKUPS_DIR/data_<timestamp>.tar.gz")"
echo "   Mode    : $($DRY_RUN && echo "DRY RUN (no changes)" || echo "live sync")"
echo "   Retain  : last $RETENTION backups"
echo ""

# Confirmation prompt (skipped with --yes or --dry-run)
if ! $DRY_RUN && ! $ASSUME_YES; then
    read -r -p "Proceed? [y/N] " reply
    if [[ ! "$reply" =~ ^[Yy]$ ]]; then
        echo "Aborted."
        exit 0
    fi
    echo ""
fi

# ── Snapshot current dest before overwriting ─────────────────────────────────
if ! $DRY_RUN && ! $SKIP_BACKUP; then
    TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
    BACKUP_FILE="$BACKUPS_DIR/data_${TIMESTAMP}.tar.gz"
    mkdir -p "$BACKUPS_DIR"

    echo "📦 Snapshotting current data/ → $(basename "$BACKUP_FILE") ..."
    # -C parent: tar from inside REPO_ROOT so paths inside the archive are
    # "data/..." rather than the full absolute path.
    tar -czf "$BACKUP_FILE" -C "$REPO_ROOT" data
    BACKUP_SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
    echo "   Saved: $BACKUP_FILE ($BACKUP_SIZE)"
    echo ""
fi

# ── Run rsync ────────────────────────────────────────────────────────────────
# Flags:
#   --archive             preserve perms, timestamps, symlinks, etc.
#   --delete              remove dest files that don't exist in source
#                         (so deletions in production propagate)
#   --human-readable      readable size output
#   --itemize-changes     one line per file change (visibility)
#   --exclude .DS_Store   macOS Finder junk
#   --exclude *.bak*      app-generated backup files (separate from our snapshots)
#
# We do NOT exclude *.example.json — those are checked into git and identical
# everywhere; rsync no-ops on them anyway since contents match.
#
# We DO sync *.npy embedding files. They're regenerable via reindex_materials(),
# but having them in sync with the JSON state means semantic search Just Works
# after the sync without a rebuild.
RSYNC_ARGS=(
    --archive
    --delete
    --human-readable
    --itemize-changes
    --exclude='.DS_Store'
    --exclude='*.bak'
    --exclude='*.bak2'
    --exclude='*.bak_*'
)

if $DRY_RUN; then
    RSYNC_ARGS+=(--dry-run)
    echo "🔍 DRY RUN — showing what would change:"
else
    echo "⏬ Syncing ..."
fi
echo ""

# Trailing slash on source matters: rsync copies CONTENTS of $SRC into $DEST,
# not the directory itself. Both ends slashed for clarity.
rsync "${RSYNC_ARGS[@]}" "$SRC/" "$DEST/"

echo ""

# ── Post-sync report ─────────────────────────────────────────────────────────
if ! $DRY_RUN; then
    DEST_FILE_COUNT=$(find "$DEST" -type f | wc -l | tr -d ' ')
    DEST_SIZE=$(du -sh "$DEST" | cut -f1)
    echo "✅ Sync complete."
    echo "   $DEST_FILE_COUNT files, $DEST_SIZE total"
    echo ""

    # Reindex hint if embeddings file might be stale
    if [[ -f "$DEST/rag_embeddings.npy" ]] && [[ -f "$DEST/rag_index.json" ]]; then
        # Compare mtimes: if index is newer than embeddings, they're out of sync
        if [[ "$DEST/rag_index.json" -nt "$DEST/rag_embeddings.npy" ]]; then
            echo "⚠️  RAG index appears newer than embeddings — consider running"
            echo "   .venv/bin/python rag.py  (or call reindex_materials() via chat)"
            echo ""
        fi
    fi
else
    echo "✅ Dry run complete. No changes made."
    echo ""
fi

# ── Prune old backups ────────────────────────────────────────────────────────
if ! $DRY_RUN && ! $SKIP_BACKUP; then
    cd "$BACKUPS_DIR"
    # Filenames are controlled (data_YYYYMMDD_HHMMSS.tar.gz, generated by us
    # via `date +%Y%m%d_%H%M%S`) so the SC2012 newline/space risk doesn't apply.
    # shellcheck disable=SC2012
    OLD_BACKUPS=$(ls -1t data_*.tar.gz 2>/dev/null | tail -n +"$((RETENTION + 1))" || true)
    if [[ -n "$OLD_BACKUPS" ]]; then
        echo "🧹 Pruning old backups (keeping last $RETENTION):"
        echo "$OLD_BACKUPS" | while read -r old; do
            echo "   rm $old"
            rm -f "$old"
        done
        echo ""
    fi
    # Same justification as above.
    # shellcheck disable=SC2012
    KEPT=$(ls -1 data_*.tar.gz 2>/dev/null | wc -l | tr -d ' ')
    echo "📦 Backups retained: $KEPT"
fi
