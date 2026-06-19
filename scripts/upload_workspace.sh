#!/usr/bin/env bash
# scripts/upload_workspace.sh
#
# Uploads workspace files to Azure Blob Storage for AKS deployment.
# Reads your local config.json to find what to upload — no hardcoded paths.
# Safe to re-run: blobs are overwritten with --overwrite true.
#
# Usage:
#   ./scripts/upload_workspace.sh
#
# Reads from config.json:
#   resume_folder     — local path, source for all *_path keys
#   leetcode_folder   — local path, source for leetcode files
#   All *_path keys   — relative paths within resume_folder or leetcode_folder
#
# Configurable via env vars:
#   STORAGE_ACCOUNT   (default: jcmcpstore; override via env or .env.deploy)
#   CONFIG_FILE       (default: config.json)

set -euo pipefail

CONFIG_FILE="${CONFIG_FILE:-config.json}"

if [[ ! -f "$CONFIG_FILE" ]]; then
  echo "ERROR: $CONFIG_FILE not found. Run from the project root."
  exit 1
fi

command -v jq >/dev/null || { echo "ERROR: jq not found. brew install jq"; exit 1; }
command -v az >/dev/null || { echo "ERROR: az not found."; exit 1; }

# Resolve storage account: env → .env.deploy → config.json → default
if [[ -z "${STORAGE_ACCOUNT:-}" ]]; then
  [[ -f .env.deploy ]] && source .env.deploy 2>/dev/null || true
fi
STORAGE_ACCOUNT="${STORAGE_ACCOUNT:-jcmcpstore}"

RESUME_FOLDER=$(jq -r '.resume_folder // ""' "$CONFIG_FILE")
LEETCODE_FOLDER=$(jq -r '.leetcode_folder // ""' "$CONFIG_FILE")

if [[ -z "$RESUME_FOLDER" ]]; then
  echo "ERROR: resume_folder not set in $CONFIG_FILE"
  exit 1
fi

echo "============================================"
echo " jobContextMCP — workspace upload"
echo " Config         : $CONFIG_FILE"
echo " Storage        : $STORAGE_ACCOUNT"
echo " Resume folder  : $RESUME_FOLDER"
echo " LeetCode folder: ${LEETCODE_FOLDER:-"(not configured)"}"
echo "============================================"
echo ""

# Use account key to avoid RBAC propagation delays
ACCT_KEY=$(az storage account keys list \
  --account-name "$STORAGE_ACCOUNT" \
  --query "[0].value" -o tsv 2>/dev/null) || {
  echo "ERROR: Could not retrieve key for storage account '$STORAGE_ACCOUNT'."
  echo "Run provision_aks.sh first, or set STORAGE_ACCOUNT correctly."
  exit 1
}

upload_blob() {
  local blob_name="$1"
  local local_path="$2"
  if [[ ! -f "$local_path" ]]; then
    echo "   SKIP (not found): $blob_name"
    return
  fi
  az storage blob upload \
    --account-name "$STORAGE_ACCOUNT" \
    --account-key "$ACCT_KEY" \
    --container-name workspace \
    --name "$blob_name" \
    --file "$local_path" \
    --overwrite true \
    --output none
  echo "   OK: $blob_name"
}

# Upload every *_path key from config.json that lives under resume_folder.
# The blob name = the relative path value (preserves directory structure).
echo ">> Uploading resume folder files..."
while IFS= read -r key; do
  rel=$(jq -r --arg k "$key" '.[$k]' "$CONFIG_FILE")
  [[ -z "$rel" || "$rel" == "null" ]] && continue
  upload_blob "$rel" "$RESUME_FOLDER/$rel"
done < <(jq -r 'keys[] | select((endswith("_path") or endswith("_png")) and (startswith("leetcode_") | not) and (startswith("quick_") | not))' "$CONFIG_FILE")

# Upload LeetCode files if configured
if [[ -n "$LEETCODE_FOLDER" ]]; then
  echo ""
  echo ">> Uploading LeetCode files..."
  while IFS= read -r key; do
    rel=$(jq -r --arg k "$key" '.[$k]' "$CONFIG_FILE")
    [[ -z "$rel" || "$rel" == "null" ]] && continue
    # Store under leetcode/ prefix so init container puts them at
    # /app/data/workspace/leetcode/ (matches leetcode_folder in k8s config)
    upload_blob "leetcode/$rel" "$LEETCODE_FOLDER/$rel"
  done < <(jq -r '[keys[] | select(startswith("leetcode_cheatsheet") or startswith("quick_reference"))] | .[]' "$CONFIG_FILE")
fi

# Bulk-upload all workspace subdirectories (source materials + all generated artifacts).
# This gives AKS a complete workspace on first seed, and keeps blob current so the
# pod sidecar has a full baseline after any pod replacement or scale event.
echo ""
echo ">> Uploading all workspace directories (complete sync)..."
WORKSPACE_DIRS=(
  "01-Current-Optimized"
  "02-Cover-Letters"
  "03-Resume-PDFs"
  "04-Archived-Resumes"
  "05-Research"
  "06-Reference-Materials"
  "07-Job-Assessments"
  "08-Interview-Prep-Docs"
  "09-Cover-Letter-PDFs"
)
for dir in "${WORKSPACE_DIRS[@]}"; do
  local_dir="$RESUME_FOLDER/$dir"
  if [[ ! -d "$local_dir" ]]; then
    echo "   SKIP (not found): $dir/"
    continue
  fi
  file_count=$(find "$local_dir" -type f | wc -l | tr -d ' ')
  if [[ "$file_count" -eq 0 ]]; then
    echo "   SKIP (empty): $dir/"
    continue
  fi
  az storage blob upload-batch \
    --account-name "$STORAGE_ACCOUNT" \
    --account-key "$ACCT_KEY" \
    --source "$local_dir" \
    --destination workspace \
    --destination-path "$dir" \
    --overwrite true \
    --output none
  echo "   OK: $dir/ ($file_count files)"
done

# Verify
echo ""
echo ">> Verifying uploaded blobs..."
az storage blob list \
  --account-name "$STORAGE_ACCOUNT" \
  --account-key "$ACCT_KEY" \
  --container-name workspace \
  --query "[].{name:name, size:properties.contentLength}" \
  --output table

echo ""
echo "============================================"
echo " Upload complete."
echo " Init container seeds the full workspace from blob on pod start."
echo " Sidecar syncs generated artifacts + DB back to blob every 15 min."
echo ""
echo " To restart the pod and pick up the new workspace:"
echo "   kubectl rollout restart deployment/jcmcp -n jcmcp"
echo "============================================"
