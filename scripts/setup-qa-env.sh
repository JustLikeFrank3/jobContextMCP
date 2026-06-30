#!/usr/bin/env bash
# scripts/setup-qa-env.sh
#
# One-time provisioning script for the QA environment on the existing AKS cluster.
# Run this ONCE from your local machine before the first QA deploy.
# Prerequisites: az CLI, kubectl, AKS context already configured.
#
# Usage:
#   chmod +x scripts/setup-qa-env.sh
#   ./scripts/setup-qa-env.sh
#
# Required env vars (or edit the DEFAULTS block below):
#   QA_STORAGE_ACCOUNT    - Name of the new QA Azure Storage account (3-24 lowercase alphanumeric)
#   ENTRA_TENANT_ID       - Azure tenant ID (az account show --query tenantId -o tsv)
#   ENTRA_CLIENT_ID       - Entra app registration client ID
#   ENTRA_CLIENT_SECRET   - Entra app registration client secret
#   LLM_API_KEY           - API key for the LLM provider (leave blank for Azure Foundry w/ workload identity)
#   ENTRA_OWNER_OID       - Frank's OID (az ad user show --id <email> --query id -o tsv)

set -euo pipefail

# ── DEFAULTS (override via env vars) ─────────────────────────────────────────
AKS_RG="${AKS_RG:-jcmcp-rg}"
AKS_CLUSTER="${AKS_CLUSTER:-jcmcp-aks}"
ACR="${ACR:-jcmcpacr.azurecr.io}"
QA_NAMESPACE="${QA_NAMESPACE:-jcmcp-qa}"
QA_STORAGE_ACCOUNT="${QA_STORAGE_ACCOUNT:-jcmcpqastore}"
AZURE_LOCATION="${AZURE_LOCATION:-eastus}"
WORKLOAD_IDENTITY_NAME="${WORKLOAD_IDENTITY_NAME:-jcmcp-workload-id}"
SERVICE_ACCOUNT_NAME="jcmcp-workload-sa"

# Must be set by the caller
: "${ENTRA_TENANT_ID:?Set ENTRA_TENANT_ID}"
: "${ENTRA_CLIENT_ID:?Set ENTRA_CLIENT_ID}"
: "${ENTRA_CLIENT_SECRET:?Set ENTRA_CLIENT_SECRET}"
: "${ENTRA_OWNER_OID:?Set ENTRA_OWNER_OID}"
LLM_API_KEY="${LLM_API_KEY:-}"   # optional for Azure Foundry w/ workload identity
LLM_PROVIDER="${LLM_PROVIDER:-foundry}"
OURA_CLIENT_ID="${OURA_CLIENT_ID:-}"       # optional: Oura Ring OAuth app client id
OURA_CLIENT_SECRET="${OURA_CLIENT_SECRET:-}"  # optional: Oura Ring OAuth app secret

# ─────────────────────────────────────────────────────────────────────────────

echo "==> Setting AKS context: $AKS_CLUSTER in $AKS_RG"
az aks get-credentials --resource-group "$AKS_RG" --name "$AKS_CLUSTER" --overwrite-existing

# 1. Create QA namespace
echo ""
echo "==> Creating namespace: $QA_NAMESPACE"
kubectl create namespace "$QA_NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -

# 2. Create QA Azure Storage account
echo ""
echo "==> Creating QA Storage account: $QA_STORAGE_ACCOUNT"
az storage account create \
  --name "$QA_STORAGE_ACCOUNT" \
  --resource-group "$AKS_RG" \
  --location "$AZURE_LOCATION" \
  --sku Standard_LRS \
  --kind StorageV2 \
  --allow-blob-public-access false \
  --output none
echo "    Creating 'workspace' container..."
az storage container create \
  --name workspace \
  --account-name "$QA_STORAGE_ACCOUNT" \
  --auth-mode login \
  --output none || echo "    (container may already exist)"

# 3. Grant the existing workload identity access to the QA storage account
echo ""
echo "==> Granting workload identity Storage Blob Data Contributor on QA storage"
WORKLOAD_IDENTITY_CLIENT_ID=$(az identity show \
  --resource-group "$AKS_RG" \
  --name "$WORKLOAD_IDENTITY_NAME" \
  --query clientId -o tsv 2>/dev/null || echo "")
QA_STORAGE_ID=$(az storage account show \
  --name "$QA_STORAGE_ACCOUNT" \
  --resource-group "$AKS_RG" \
  --query id -o tsv)
if [ -n "$WORKLOAD_IDENTITY_CLIENT_ID" ]; then
  az role assignment create \
    --role "Storage Blob Data Contributor" \
    --assignee "$WORKLOAD_IDENTITY_CLIENT_ID" \
    --scope "$QA_STORAGE_ID" \
    --output none || echo "    (role assignment may already exist)"
  echo "    Workload identity $WORKLOAD_IDENTITY_NAME granted access."
else
  echo "    WARNING: Could not find workload identity '$WORKLOAD_IDENTITY_NAME'."
  echo "    Grant 'Storage Blob Data Contributor' on $QA_STORAGE_ID manually."
fi

# 4. Create service account in QA namespace with workload identity annotation
echo ""
echo "==> Creating service account in $QA_NAMESPACE"
if [ -n "$WORKLOAD_IDENTITY_CLIENT_ID" ]; then
  kubectl create serviceaccount "$SERVICE_ACCOUNT_NAME" \
    --namespace "$QA_NAMESPACE" \
    --dry-run=client -o yaml \
    | kubectl annotate --local -f - \
        "azure.workload.identity/client-id=$WORKLOAD_IDENTITY_CLIENT_ID" \
        --overwrite -o yaml \
    | kubectl apply -f -
else
  kubectl create serviceaccount "$SERVICE_ACCOUNT_NAME" \
    --namespace "$QA_NAMESPACE" \
    --dry-run=client -o yaml | kubectl apply -f -
  echo "    WARNING: Annotate the service account with the workload identity client ID manually:"
  echo "    kubectl annotate sa $SERVICE_ACCOUNT_NAME -n $QA_NAMESPACE azure.workload.identity/client-id=<CLIENT_ID>"
fi

# 5. Add federated credential for the QA namespace service account
#    (allows the same managed identity to authenticate from jcmcp-qa namespace)
echo ""
echo "==> Adding federated credential for QA service account"
AKS_OIDC_ISSUER=$(az aks show \
  --resource-group "$AKS_RG" \
  --name "$AKS_CLUSTER" \
  --query "oidcIssuerProfile.issuerUrl" -o tsv)
az identity federated-credential create \
  --name "jcmcp-qa-federated-cred" \
  --identity-name "$WORKLOAD_IDENTITY_NAME" \
  --resource-group "$AKS_RG" \
  --issuer "$AKS_OIDC_ISSUER" \
  --subject "system:serviceaccount:${QA_NAMESPACE}:${SERVICE_ACCOUNT_NAME}" \
  --output none || echo "    (federated credential may already exist)"
echo "    Federated credential added for $QA_NAMESPACE/$SERVICE_ACCOUNT_NAME"

# 6. Create the QA K8s secret (jcmcp-qa-app-secrets)
echo ""
echo "==> Creating jcmcp-qa-app-secrets in $QA_NAMESPACE"
kubectl create secret generic jcmcp-qa-app-secrets \
  --namespace "$QA_NAMESPACE" \
  --from-literal=server_base_url="https://qa.jobcontext.ai" \
  --from-literal=entra_tenant_id="$ENTRA_TENANT_ID" \
  --from-literal=entra_client_id="$ENTRA_CLIENT_ID" \
  --from-literal=entra_client_secret="$ENTRA_CLIENT_SECRET" \
  --from-literal=llm_provider="$LLM_PROVIDER" \
  --from-literal=llm_api_key="$LLM_API_KEY" \
  --from-literal=oura_client_id="$OURA_CLIENT_ID" \
  --from-literal=oura_client_secret="$OURA_CLIENT_SECRET" \
  --dry-run=client -o yaml | kubectl apply -f -

# 7. Apply static QA manifests (PVC and Service don't have placeholders)
echo ""
echo "==> Applying QA PVC and Service"
kubectl apply -f k8s/qa/pvc.yaml
kubectl apply -f k8s/qa/service.yaml

echo ""
echo "══════════════════════════════════════════════════════════════════════"
echo "QA namespace provisioned. Two manual steps remain:"
echo ""
echo "  1. DNS — Add a CNAME (or A record) for qa.jobcontext.ai:"
echo "     Target: $(kubectl get svc -n ingress-nginx ingress-nginx-controller -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || echo '<AKS-ingress-public-IP>')"
echo "     (look up the IP with: kubectl get svc -n ingress-nginx)"
echo ""
echo "  2. Entra app registration — Add redirect URI:"
echo "     https://qa.jobcontext.ai/dashboard/callback"
echo "     (Azure Portal → App registrations → your app → Authentication)"
echo "     NOTE: the callback path is /dashboard/callback (matches SERVER_BASE_URL"
echo "           + the login router prefix), not /auth/callback."
echo ""
echo "  3. GitHub secret — Add to JustLikeFrank3/jobContextMCP:"
echo "     QA_STORAGE_ACCOUNT = $QA_STORAGE_ACCOUNT"
echo "     (Settings → Secrets → Actions → New repository secret)"
echo ""
echo "  4. (Optional) Oura Ring — to enable the Connect flow:"
echo "     Register an app at https://cloud.ouraring.com/oauth/applications"
echo "     Redirect URI: https://qa.jobcontext.ai/dashboard/oura/callback"
echo "     Then re-run this script with OURA_CLIENT_ID and OURA_CLIENT_SECRET set,"
echo "     or patch jcmcp-qa-app-secrets, and restart the deployment."
echo ""
echo "Once DNS propagates (~5 min) push to qa branch to trigger the first deploy."
echo "══════════════════════════════════════════════════════════════════════"
