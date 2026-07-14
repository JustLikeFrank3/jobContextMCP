#!/usr/bin/env bash
# local-cluster.sh — stand up / tear down a local k3d cluster running the
# jcmcp container from k8s/local/ manifests.  See docs/local-cluster.md.
#
#   ./scripts/local-cluster.sh up        create cluster, build+import image, deploy
#   ./scripts/local-cluster.sh rebuild   rebuild image, import, restart pod
#   ./scripts/local-cluster.sh apply     re-apply manifests + secrets (no image build)
#   ./scripts/local-cluster.sh status    pod/service state
#   ./scripts/local-cluster.sh logs      follow app logs
#   ./scripts/local-cluster.sh down      delete the cluster (and its data)
#
# Secrets/config come from .env.local at the repo root (gitignored; see
# .env.local.example).  Without it the app runs with auth disabled and no
# LLM provider — fine for smoke tests.
#
# kubectl context safety: the k3d context is created but NEVER activated —
# every kubectl call below pins --context, so your current context (e.g.
# AKS prod) is left untouched.

set -euo pipefail

CLUSTER=jcmcp-local
CTX=k3d-${CLUSTER}
NS=jcmcp-local
IMAGE=jcmcp:local
HOST_PORT=8080
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
K8S_DIR="${ROOT}/k8s/local"
ENV_FILE="${ROOT}/.env.local"

k() { kubectl --context "${CTX}" "$@"; }

need() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "ERROR: '$1' not found. $2" >&2
    exit 1
  }
}

check_deps() {
  need docker "Install Docker and make sure the daemon is running."
  need k3d "Install: https://k3d.io/#installation"
  need kubectl "Install kubectl."
}

load_env() {
  if [ -f "${ENV_FILE}" ]; then
    set -a
    # shellcheck disable=SC1090
    . "${ENV_FILE}"
    set +a
  else
    echo "NOTE: ${ENV_FILE} not found — deploying with auth disabled and no LLM key."
    echo "      Copy .env.local.example to .env.local to configure Entra/LLM."
  fi
}

cluster_up() {
  if k3d cluster list -o json | grep -q "\"name\":\"${CLUSTER}\""; then
    echo "Cluster ${CLUSTER} already exists."
  else
    # Traefik is disabled so it doesn't claim node port 80 — the app is
    # exposed via ServiceLB (type LoadBalancer), not ingress.
    k3d cluster create "${CLUSTER}" \
      --port "${HOST_PORT}:80@loadbalancer" \
      --k3s-arg "--disable=traefik@server:0" \
      --kubeconfig-update-default \
      --kubeconfig-switch-context=false \
      --wait
  fi
}

build_import() {
  docker build -t "${IMAGE}" "${ROOT}"
  k3d image import "${IMAGE}" -c "${CLUSTER}"
}

apply_all() {
  k create namespace "${NS}" --dry-run=client -o yaml | k apply -f -

  k -n "${NS}" create secret generic jcmcp-local-app-secrets \
    --from-literal=entra_tenant_id="${LOCAL_ENTRA_TENANT_ID:-}" \
    --from-literal=entra_client_id="${LOCAL_ENTRA_CLIENT_ID:-}" \
    --from-literal=entra_client_secret="${LOCAL_ENTRA_CLIENT_SECRET:-}" \
    --from-literal=api_key="${LOCAL_API_KEY:-}" \
    --from-literal=llm_provider="${LOCAL_LLM_PROVIDER:-}" \
    --from-literal=llm_api_key="${LOCAL_LLM_API_KEY:-}" \
    --from-literal=oura_client_id="${LOCAL_OURA_CLIENT_ID:-}" \
    --from-literal=oura_client_secret="${LOCAL_OURA_CLIENT_SECRET:-}" \
    --from-literal=app_encryption_key="${LOCAL_APP_ENCRYPTION_KEY:-}" \
    --dry-run=client -o yaml | k apply -f -

  sed \
    -e "s|__LOCAL_LLM_PROVIDER__|${LOCAL_LLM_PROVIDER:-}|g" \
    -e "s|__LOCAL_FOUNDRY_ENDPOINT__|${LOCAL_FOUNDRY_ENDPOINT:-}|g" \
    -e "s|__LOCAL_FOUNDRY_DEPLOYMENT__|${LOCAL_FOUNDRY_DEPLOYMENT:-}|g" \
    -e "s|__LOCAL_FOUNDRY_API_VERSION__|${LOCAL_FOUNDRY_API_VERSION:-}|g" \
    -e "s|__LOCAL_ENTRA_OWNER_OID__|${LOCAL_ENTRA_OWNER_OID:-}|g" \
    "${K8S_DIR}/configmap.yaml" | k apply -f -

  k apply -f "${K8S_DIR}/pvc.yaml"
  k apply -f "${K8S_DIR}/service.yaml"
  k apply -f "${K8S_DIR}/deployment.yaml"
}

restart_wait() {
  # Secrets/config are only read at process start, and a static image tag
  # needs a restart to pick up a re-imported build.
  k -n "${NS}" rollout restart deployment/jcmcp-local
  k -n "${NS}" rollout status deployment/jcmcp-local --timeout=180s
}

wait_ready() {
  k -n "${NS}" rollout status deployment/jcmcp-local --timeout=180s
}

print_url() {
  echo
  echo "jcmcp is up: http://localhost:${HOST_PORT}"
  echo "  dashboard  http://localhost:${HOST_PORT}/dashboard"
  echo "  health     http://localhost:${HOST_PORT}/health"
  echo "  metrics    http://localhost:${HOST_PORT}/metrics"
  echo "kubectl access: kubectl --context ${CTX} -n ${NS} ..."
}

case "${1:-}" in
  up)
    check_deps
    load_env
    cluster_up
    build_import
    apply_all
    wait_ready
    print_url
    ;;
  rebuild)
    check_deps
    build_import
    restart_wait
    print_url
    ;;
  apply)
    check_deps
    load_env
    apply_all
    restart_wait
    print_url
    ;;
  status)
    k -n "${NS}" get pods,svc,pvc
    ;;
  logs)
    k -n "${NS}" logs -f deployment/jcmcp-local
    ;;
  down)
    k3d cluster delete "${CLUSTER}"
    ;;
  *)
    sed -n '2,16p' "$0"
    exit 1
    ;;
esac
