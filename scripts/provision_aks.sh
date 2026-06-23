#!/usr/bin/env bash
# scripts/provision_aks.sh
#
# One-time Azure infrastructure provisioning for jobContextMCP.
# Creates all cloud resources needed to run the server in AKS.
# Contains NO user-specific filenames or paths.
#
# Usage:
#   ./scripts/provision_aks.sh
#
# Configurable via env vars (all have sensible defaults):
#   AKS_RG           Resource group name          (default: jcmcp-rg)
#   AKS_CLUSTER      AKS cluster name             (default: jcmcp-aks)
#   ACR_NAME         Container registry name      (default: jcmcpacr)
#   STORAGE_ACCOUNT  Storage account name         (default: jcmcpstore)
#   LOCATION         Azure region                 (default: eastus)
#
# After running this, upload your workspace files:
#   ./scripts/upload_workspace.sh
#
# Prerequisites: az login, docker, kubectl

set -euo pipefail

AKS_RG="${AKS_RG:-jcmcp-rg}"
AKS_CLUSTER="${AKS_CLUSTER:-jcmcp-aks}"
ACR_NAME="${ACR_NAME:-jcmcpacr}"
STORAGE_ACCOUNT="${STORAGE_ACCOUNT:-jcmcpstore}"
NODE_VM_SIZE="${NODE_VM_SIZE:-Standard_D2s_v3}"
LOCATION="${LOCATION:-eastus}"
NAMESPACE="jcmcp"
WORKLOAD_ID_NAME="jcmcp-workload-id"
SERVICE_ACCOUNT_NAME="jcmcp-workload-sa"

echo "============================================"
echo " jobContextMCP — AKS provisioning"
echo " Resource Group    : $AKS_RG"
echo " AKS Cluster       : $AKS_CLUSTER"
echo " ACR               : ${ACR_NAME}.azurecr.io"
echo " Storage Account   : $STORAGE_ACCOUNT"
echo " Node VM Size      : $NODE_VM_SIZE"
echo " Location          : $LOCATION"
echo "============================================"

# ── 0. Prerequisites ──────────────────────────────────────────────────────────
for cmd in az docker kubectl jq; do
  command -v "$cmd" >/dev/null || { echo "ERROR: $cmd not found. Install it first."; exit 1; }
done

SUBSCRIPTION_ID=$(az account show --query id -o tsv)
TENANT_ID=$(az account show --query tenantId -o tsv)
OPERATOR_OID=$(az ad signed-in-user show --query id -o tsv)
echo "Subscription : $SUBSCRIPTION_ID"
echo "Tenant       : $TENANT_ID"
echo ""

# ── 1. Register providers (idempotent) ────────────────────────────────────────
echo ">> Registering resource providers..."
for ns in Microsoft.ContainerRegistry Microsoft.ContainerService Microsoft.Storage Microsoft.ManagedIdentity; do
  state=$(az provider show --namespace "$ns" --query registrationState -o tsv 2>/dev/null || echo "NotRegistered")
  if [[ "$state" != "Registered" ]]; then
    az provider register --namespace "$ns" --wait --output none
    echo "   registered: $ns"
  else
    echo "   already registered: $ns"
  fi
done

# ── 2. Resource group ─────────────────────────────────────────────────────────
echo ""
echo ">> Resource group..."
az group create --name "$AKS_RG" --location "$LOCATION" --output none
echo "   $AKS_RG"

# ── 3. Container Registry ────────────────────────────────────────────────────
echo ""
echo ">> Container Registry..."
az acr create --resource-group "$AKS_RG" --name "$ACR_NAME" --sku Basic --output none 2>/dev/null || true
echo "   ${ACR_NAME}.azurecr.io"

# ── 4. Storage Account + workspace container ──────────────────────────────────
echo ""
echo ">> Storage Account..."
az storage account create \
  --resource-group "$AKS_RG" \
  --name "$STORAGE_ACCOUNT" \
  --location "$LOCATION" \
  --sku Standard_LRS \
  --allow-blob-public-access false \
  --output none 2>/dev/null || true

STORAGE_ID=$(az storage account show --name "$STORAGE_ACCOUNT" --resource-group "$AKS_RG" --query id -o tsv)
echo "   $STORAGE_ACCOUNT (id: $STORAGE_ID)"

# Grant operator upload rights for upload_workspace.sh
az role assignment create \
  --assignee-object-id "$OPERATOR_OID" \
  --assignee-principal-type User \
  --role "Storage Blob Data Contributor" \
  --scope "$STORAGE_ID" \
  --output none 2>/dev/null || true
echo "   Granted Storage Blob Data Contributor to operator, waiting for propagation..."
sleep 20

ACCT_KEY=$(az storage account keys list --account-name "$STORAGE_ACCOUNT" --resource-group "$AKS_RG" --query "[0].value" -o tsv)
az storage container create \
  --account-name "$STORAGE_ACCOUNT" \
  --account-key "$ACCT_KEY" \
  --name workspace \
  --output none 2>/dev/null || true
echo "   container 'workspace' ready"

# ── 5. AKS cluster ────────────────────────────────────────────────────────────
echo ""
echo ">> AKS cluster (this takes ~8 min)..."
if az aks show --resource-group "$AKS_RG" --name "$AKS_CLUSTER" --output none 2>/dev/null; then
  echo "   cluster already exists — skipping create"
else
  az aks create \
    --resource-group "$AKS_RG" \
    --name "$AKS_CLUSTER" \
    --node-count 1 \
    --node-vm-size "$NODE_VM_SIZE" \
    --enable-oidc-issuer \
    --enable-workload-identity \
    --attach-acr "$ACR_NAME" \
    --generate-ssh-keys \
    --output none
fi
echo "   cluster ready"

OIDC_ISSUER=$(az aks show --resource-group "$AKS_RG" --name "$AKS_CLUSTER" \
  --query "oidcIssuerProfile.issuerUrl" -o tsv)

# ── 6. Workload Identity ──────────────────────────────────────────────────────
echo ""
echo ">> Workload identity..."
az identity create --resource-group "$AKS_RG" --name "$WORKLOAD_ID_NAME" --output none 2>/dev/null || true

IDENTITY_CLIENT_ID=$(az identity show --resource-group "$AKS_RG" --name "$WORKLOAD_ID_NAME" --query clientId -o tsv)
IDENTITY_OBJECT_ID=$(az identity show --resource-group "$AKS_RG" --name "$WORKLOAD_ID_NAME" --query principalId -o tsv)
echo "   client_id: $IDENTITY_CLIENT_ID"

# Grant pod read access to Blob Storage (for init container workspace seed)
az role assignment create \
  --assignee-object-id "$IDENTITY_OBJECT_ID" \
  --assignee-principal-type ServicePrincipal \
  --role "Storage Blob Data Reader" \
  --scope "$STORAGE_ID" \
  --output none 2>/dev/null || true
echo "   Storage Blob Data Reader granted to workload identity"

# Grant workload identity access to call the Foundry/OpenAI deployment
# (only wired when provider is foundry — no-op for openai/ollama)
if [[ "${LLM_PROVIDER:-}" == "foundry" && -n "${FOUNDRY_ENDPOINT:-}" ]]; then
  FOUNDRY_RESOURCE_NAME=$(echo "$FOUNDRY_ENDPOINT" | sed 's|https://||;s|\..*||')
  FOUNDRY_RESOURCE_ID=$(az cognitiveservices account show \
    --name "$FOUNDRY_RESOURCE_NAME" \
    --query id -o tsv 2>/dev/null || echo "")
  if [[ -n "$FOUNDRY_RESOURCE_ID" ]]; then
    az role assignment create \
      --assignee-object-id "$IDENTITY_OBJECT_ID" \
      --assignee-principal-type ServicePrincipal \
      --role "Cognitive Services User" \
      --scope "$FOUNDRY_RESOURCE_ID" \
      --output none 2>/dev/null || true
    echo "   Cognitive Services User granted to workload identity on $FOUNDRY_RESOURCE_NAME"
  else
    echo "   WARN: Could not find Foundry resource '$FOUNDRY_RESOURCE_NAME' — grant role manually"
  fi
fi

# Federated credential — lets the k8s SA assume the managed identity
az identity federated-credential create \
  --name "jcmcp-federated" \
  --identity-name "$WORKLOAD_ID_NAME" \
  --resource-group "$AKS_RG" \
  --issuer "$OIDC_ISSUER" \
  --subject "system:serviceaccount:${NAMESPACE}:${SERVICE_ACCOUNT_NAME}" \
  --output none 2>/dev/null || true

# ── 7. k8s namespace + service account ───────────────────────────────────────
echo ""
echo ">> Kubernetes setup..."
az aks get-credentials --resource-group "$AKS_RG" --name "$AKS_CLUSTER" --overwrite-existing

kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -
kubectl create serviceaccount "$SERVICE_ACCOUNT_NAME" --namespace "$NAMESPACE" \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl annotate serviceaccount "$SERVICE_ACCOUNT_NAME" --namespace "$NAMESPACE" \
  --overwrite azure.workload.identity/client-id="$IDENTITY_CLIENT_ID"

# ── 8. LLM provider selection ────────────────────────────────────────────────
echo ""
echo ">> LLM provider setup..."

if [[ -z "${LLM_PROVIDER:-}" ]]; then
  echo "   Choose LLM provider:"
  echo "     1) openai   — api.openai.com"
  echo "     2) foundry  — Azure AI Foundry (recommended if you have a deployment)"
  echo "     3) ollama   — local Ollama endpoint (no API key needed)"
  read -rp "   Enter choice [1/2/3, default=2]: " provider_choice
  case "${provider_choice:-2}" in
    1) LLM_PROVIDER="openai" ;;
    3) LLM_PROVIDER="ollama" ;;
    *) LLM_PROVIDER="foundry" ;;
  esac
fi
echo "   Provider: $LLM_PROVIDER"

LLM_API_KEY=""
FOUNDRY_ENDPOINT=""
FOUNDRY_DEPLOYMENT="gpt-4o"
FOUNDRY_API_VERSION="2024-10-21"

case "$LLM_PROVIDER" in
  foundry)
    if [[ -z "${AZURE_FOUNDRY_ENDPOINT:-}" ]]; then
      read -rp "   Azure Foundry endpoint (e.g. https://YOUR-RESOURCE.services.ai.azure.com): " FOUNDRY_ENDPOINT
    else
      FOUNDRY_ENDPOINT="$AZURE_FOUNDRY_ENDPOINT"
    fi
    if [[ -z "${AZURE_FOUNDRY_DEPLOYMENT:-}" ]]; then
      read -rp "   Deployment name [default: gpt-4.1-mini]: " dep_input
      FOUNDRY_DEPLOYMENT="${dep_input:-gpt-4.1-mini}"
    else
      FOUNDRY_DEPLOYMENT="$AZURE_FOUNDRY_DEPLOYMENT"
    fi
    # Foundry uses DefaultAzureCredential (workload identity in AKS, az login locally)
    # No API key needed — leave LLM_API_KEY empty.
    echo "   Auth: DefaultAzureCredential (no API key required)"
    ;;
  openai)
    if [[ -z "${LLM_API_KEY:-}" ]]; then
      read -rsp "   OpenAI API key: " LLM_API_KEY; echo ""
    fi
    ;;
  ollama)
    echo "   No API key needed for Ollama."
    ;;
esac

kubectl create secret generic jcmcp-app-secrets \
  --namespace "$NAMESPACE" \
  --from-literal=llm_provider="$LLM_PROVIDER" \
  --from-literal=llm_api_key="$LLM_API_KEY" \
  --dry-run=client -o yaml | kubectl apply -f -

# ── 9. Apply k8s manifests (fill LLM placeholders in configmap) ──────────────
echo ""
echo ">> Applying Kubernetes manifests..."
kubectl apply -f k8s/pvc.yaml

# Fill configmap template placeholders with resolved values
sed \
  -e "s|__LLM_PROVIDER__|${LLM_PROVIDER}|g" \
  -e "s|__FOUNDRY_ENDPOINT__|${FOUNDRY_ENDPOINT}|g" \
  -e "s|__FOUNDRY_DEPLOYMENT__|${FOUNDRY_DEPLOYMENT}|g" \
  -e "s|__FOUNDRY_API_VERSION__|${FOUNDRY_API_VERSION}|g" \
  -e "s|__STORAGE_ACCOUNT__|${STORAGE_ACCOUNT}|g" \
  -e "s|__ENTRA_OWNER_OID__|${ENTRA_OWNER_OID}|g" \
  k8s/configmap.yaml | kubectl apply -f -

kubectl apply -f k8s/service.yaml

# ── 10. Build + push image, deploy ───────────────────────────────────────────
echo ""
echo ">> Building and pushing image..."
IMAGE_TAG=$(git rev-parse --short HEAD)
az acr build --registry "$ACR_NAME" --image "jcmcp:${IMAGE_TAG}" . 2>&1 | tail -3

sed "s|<ACR_NAME>.azurecr.io/jcmcp:<IMAGE_TAG>|${ACR_NAME}.azurecr.io/jcmcp:${IMAGE_TAG}|g" \
  k8s/deployment.yaml | kubectl apply -f -

# ── 11. Write .env.deploy for future scripts ──────────────────────────────────
cat > .env.deploy << ENVEOF
# Generated by provision_aks.sh — source this in other scripts
export AKS_RG="$AKS_RG"
export AKS_CLUSTER="$AKS_CLUSTER"
export ACR_NAME="$ACR_NAME"
export STORAGE_ACCOUNT="$STORAGE_ACCOUNT"
export NAMESPACE="$NAMESPACE"
export TENANT_ID="$TENANT_ID"
export IDENTITY_CLIENT_ID="$IDENTITY_CLIENT_ID"
export LLM_PROVIDER="$LLM_PROVIDER"
export FOUNDRY_ENDPOINT="$FOUNDRY_ENDPOINT"
export FOUNDRY_DEPLOYMENT="$FOUNDRY_DEPLOYMENT"
ENVEOF
echo "   wrote .env.deploy"

echo ""
echo "============================================"
echo " DONE."
echo ""
echo " Upload your workspace files:"
echo "   ./scripts/upload_workspace.sh"
echo ""
echo " Watch rollout:"
echo "   kubectl rollout status deployment/jcmcp -n jcmcp"
echo ""
echo " Access the server:"
echo "   kubectl port-forward svc/jcmcp 8099:80 -n jcmcp"
echo "   open http://localhost:8099/dashboard"
echo "============================================"
