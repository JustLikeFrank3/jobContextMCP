#!/usr/bin/env bash
# scripts/seed_keyvault.sh
#
# One-time setup: provisions Azure infrastructure and uploads static workspace
# files to Key Vault so the AKS pod can pull them via the CSI driver.
#
# Run this ONCE from your local machine (not the container).
# Safe to re-run — `az keyvault secret set` updates in place.
#
# Usage:
#   export RESUME_FOLDER="/path/to/your/Resume 2025"
#   export LEETCODE_FOLDER="/path/to/LeetCodePractice"
#   ./scripts/seed_keyvault.sh
#
# Required env vars (or edit defaults below):
#   RESUME_FOLDER    — local path to resume folder
#   LEETCODE_FOLDER  — local path to LeetCode folder
#   AKS_RG           — Azure resource group name
#   AKS_CLUSTER      — AKS cluster name
#   ACR_NAME         — Azure Container Registry name (no .azurecr.io)
#   KV_NAME          — Key Vault name (default: jcmcp-kv)
#   LOCATION         — Azure region (default: eastus)

set -euo pipefail

# ── Config — edit these or export before running ──────────────────────────────
AKS_RG="${AKS_RG:-jcmcp-rg}"
AKS_CLUSTER="${AKS_CLUSTER:-jcmcp-aks}"
ACR_NAME="${ACR_NAME:-jcmcpacr}"
KV_NAME="${KV_NAME:-jcmcp-kv}"
LOCATION="${LOCATION:-eastus}"
NAMESPACE="jcmcp"
WORKLOAD_ID_NAME="jcmcp-workload-id"
SERVICE_ACCOUNT_NAME="jcmcp-workload-sa"

RESUME_FOLDER="${RESUME_FOLDER:?Set RESUME_FOLDER to your local Resume folder path}"
LEETCODE_FOLDER="${LEETCODE_FOLDER:?Set LEETCODE_FOLDER to your local LeetCode folder path}"

echo "============================================"
echo " jobContextMCP — Key Vault seed script"
echo " Resource Group : $AKS_RG"
echo " Key Vault      : $KV_NAME"
echo " AKS Cluster    : $AKS_CLUSTER"
echo " Location       : $LOCATION"
echo "============================================"
echo ""

# ── 0. Prerequisites check ────────────────────────────────────────────────────
for cmd in az docker kubectl; do
  command -v "$cmd" >/dev/null || { echo "ERROR: $cmd not found"; exit 1; }
done

SUBSCRIPTION_ID=$(az account show --query id -o tsv)
TENANT_ID=$(az account show --query tenantId -o tsv)
echo "Subscription : $SUBSCRIPTION_ID"
echo "Tenant       : $TENANT_ID"
echo ""

# ── 1. Resource group ─────────────────────────────────────────────────────────
echo ">> Creating resource group..."
az group create --name "$AKS_RG" --location "$LOCATION" --output none

# ── 2. Azure Container Registry ──────────────────────────────────────────────
echo ">> Creating ACR..."
az acr create \
  --resource-group "$AKS_RG" \
  --name "$ACR_NAME" \
  --sku Basic \
  --output none
echo "   ACR: ${ACR_NAME}.azurecr.io"

# ── 3. Key Vault ──────────────────────────────────────────────────────────────
echo ">> Creating Key Vault..."
az keyvault create \
  --resource-group "$AKS_RG" \
  --name "$KV_NAME" \
  --location "$LOCATION" \
  --enable-rbac-authorization true \
  --output none
KV_RESOURCE_ID=$(az keyvault show --name "$KV_NAME" --query id -o tsv)
echo "   Key Vault ID: $KV_RESOURCE_ID"

# ── 4. Upload static workspace files ─────────────────────────────────────────
echo ""
echo ">> Uploading workspace files to Key Vault..."

upload_secret() {
  local secret_name="$1"
  local file_path="$2"
  if [[ ! -f "$file_path" ]]; then
    echo "   WARN: file not found — skipping $secret_name ($file_path)"
    return
  fi
  az keyvault secret set \
    --vault-name "$KV_NAME" \
    --name "$secret_name" \
    --file "$file_path" \
    --output none
  echo "   uploaded: $secret_name"
}

upload_secret "workspace-master-resume" \
  "$RESUME_FOLDER/01-Current-Optimized/Frank MacBride Resume - MASTER SOURCE WITH METRICS.txt"

upload_secret "workspace-template-format" \
  "$RESUME_FOLDER/06-Reference-Materials/Frank MacBride Resume - Template Format.txt"

upload_secret "workspace-gm-awards" \
  "$RESUME_FOLDER/06-Reference-Materials/GM Recognition Awards.txt"

upload_secret "workspace-feedback-received" \
  "$RESUME_FOLDER/06-Reference-Materials/Feedback_Received.txt"

upload_secret "workspace-skills-shorter" \
  "$RESUME_FOLDER/06-Reference-Materials/Skills - 10% Shorter.txt"

upload_secret "workspace-leetcode-cheatsheet" \
  "$LEETCODE_FOLDER/GM_Interview_Cheatsheet.md"

upload_secret "workspace-quick-reference" \
  "$LEETCODE_FOLDER/INTERVIEW_DAY_QUICK_REFERENCE.md"

# ── 5. AKS cluster ────────────────────────────────────────────────────────────
echo ""
echo ">> Creating AKS cluster (this takes ~5 min)..."
az aks create \
  --resource-group "$AKS_RG" \
  --name "$AKS_CLUSTER" \
  --node-count 1 \
  --node-vm-size Standard_B2s \
  --enable-addons azure-keyvault-secrets-provider \
  --enable-oidc-issuer \
  --enable-workload-identity \
  --attach-acr "$ACR_NAME" \
  --generate-ssh-keys \
  --output none
echo "   AKS cluster created."

OIDC_ISSUER=$(az aks show \
  --resource-group "$AKS_RG" \
  --name "$AKS_CLUSTER" \
  --query "oidcIssuerProfile.issuerUrl" -o tsv)

# ── 6. Workload Identity ──────────────────────────────────────────────────────
echo ""
echo ">> Creating workload identity..."
az identity create \
  --resource-group "$AKS_RG" \
  --name "$WORKLOAD_ID_NAME" \
  --output none

IDENTITY_CLIENT_ID=$(az identity show \
  --resource-group "$AKS_RG" \
  --name "$WORKLOAD_ID_NAME" \
  --query clientId -o tsv)

IDENTITY_OBJECT_ID=$(az identity show \
  --resource-group "$AKS_RG" \
  --name "$WORKLOAD_ID_NAME" \
  --query principalId -o tsv)

echo "   Client ID : $IDENTITY_CLIENT_ID"

# Grant identity access to Key Vault secrets
echo ">> Granting Key Vault Secrets User role to workload identity..."
az role assignment create \
  --assignee-object-id "$IDENTITY_OBJECT_ID" \
  --assignee-principal-type ServicePrincipal \
  --role "Key Vault Secrets User" \
  --scope "$KV_RESOURCE_ID" \
  --output none

# Federated credential so the k8s service account can assume this identity
az identity federated-credential create \
  --name "jcmcp-federated" \
  --identity-name "$WORKLOAD_ID_NAME" \
  --resource-group "$AKS_RG" \
  --issuer "$OIDC_ISSUER" \
  --subject "system:serviceaccount:${NAMESPACE}:${SERVICE_ACCOUNT_NAME}" \
  --output none

# ── 7. k8s namespace + service account ───────────────────────────────────────
echo ""
echo ">> Configuring kubectl..."
az aks get-credentials \
  --resource-group "$AKS_RG" \
  --name "$AKS_CLUSTER" \
  --overwrite-existing

kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -

kubectl create serviceaccount "$SERVICE_ACCOUNT_NAME" \
  --namespace "$NAMESPACE" \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl annotate serviceaccount "$SERVICE_ACCOUNT_NAME" \
  --namespace "$NAMESPACE" \
  --overwrite \
  azure.workload.identity/client-id="$IDENTITY_CLIENT_ID"

# ── 8. k8s Secret for app secrets (OpenAI key, etc.) ─────────────────────────
echo ""
echo ">> Creating k8s app secrets..."
read -rsp "Enter OPENAI_API_KEY: " OPENAI_KEY; echo ""
kubectl create secret generic jcmcp-app-secrets \
  --namespace "$NAMESPACE" \
  --from-literal=openai_api_key="$OPENAI_KEY" \
  --dry-run=client -o yaml | kubectl apply -f -

# ── 9. Patch SecretProviderClass with resolved IDs ───────────────────────────
echo ""
echo ">> Patching SecretProviderClass with resolved IDs..."
sed \
  -e "s|<TENANT_ID>|${TENANT_ID}|g" \
  -e "s|<CLIENT_ID>|${IDENTITY_CLIENT_ID}|g" \
  k8s/secret-provider-class.yaml | kubectl apply -f -

# Apply remaining manifests
kubectl apply -f k8s/pvc.yaml
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/service.yaml

# ── 10. Build and push image ──────────────────────────────────────────────────
echo ""
echo ">> Building and pushing image to ACR..."
IMAGE_TAG=$(git rev-parse --short HEAD)
az acr build \
  --registry "$ACR_NAME" \
  --image "jcmcp:${IMAGE_TAG}" \
  .

# Patch image tag in deployment and apply
sed "s|<ACR_NAME>.azurecr.io/jcmcp:<IMAGE_TAG>|${ACR_NAME}.azurecr.io/jcmcp:${IMAGE_TAG}|g" \
  k8s/deployment.yaml | kubectl apply -f -

# ── 11. Summary ───────────────────────────────────────────────────────────────
echo ""
echo "============================================"
echo " DONE. To access the running pod:"
echo ""
echo "   kubectl port-forward svc/jcmcp 8099:80 -n jcmcp"
echo "   open http://localhost:8099/dashboard"
echo ""
echo " To watch rollout:"
echo "   kubectl rollout status deployment/jcmcp -n jcmcp"
echo ""
echo " To check init container logs:"
echo "   kubectl logs -n jcmcp -l app=jcmcp -c seed-workspace"
echo ""
echo " SecretProviderClass values for future reference:"
echo "   TENANT_ID : $TENANT_ID"
echo "   CLIENT_ID : $IDENTITY_CLIENT_ID"
echo "============================================"
