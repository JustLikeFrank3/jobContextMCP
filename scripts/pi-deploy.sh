#!/usr/bin/env bash
# pi-deploy.sh — build the arm64 image and deploy jcmcp to the k3s cluster
# on the Pi (Node1) over the direct ethernet link.  See docs/local-cluster.md.
#
#   ./scripts/pi-deploy.sh deploy    build arm64 image, ship it, apply manifests
#   ./scripts/pi-deploy.sh apply     re-apply manifests + secrets (no image build)
#   ./scripts/pi-deploy.sh kubeconfig  fetch kubeconfig to ~/.kube/pi-node1.yaml
#   ./scripts/pi-deploy.sh status    pod/service state
#   ./scripts/pi-deploy.sh logs      follow app logs
#   ./scripts/pi-deploy.sh monitoring  deploy Prometheus+Grafana (k8s/monitoring/
#                                      adapted: local-path storage, jcmcp-pi
#                                      scrape ns, Grafana on LAN port 3000)
#   ./scripts/pi-deploy.sh backup-setup  install scripts/pi-backup.sh on the Pi
#                                        + nightly systemd timer (03:30) writing
#                                        to the USB drive at /mnt/backup
#
# Assumes: SSH alias pi-node1 (direct link, 192.168.101.2) with passwordless
# sudo, k3s installed on the Pi, and qemu binfmt for arm64 cross-builds
# (docker run --privileged --rm tonistiigi/binfmt --install arm64).
#
# Secrets/config come from .env.pi at the repo root (gitignored) — same
# variable names as .env.local.example but with PI_ prefix substitutions;
# falls back to no-auth/no-LLM when absent.

set -euo pipefail

PI=pi-node1
NS=jcmcp-pi
IMAGE=jcmcp:pi
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
K8S_DIR="${ROOT}/k8s/pi"
ENV_FILE="${ROOT}/.env.pi"
KUBECONFIG_OUT="${HOME}/.kube/pi-node1.yaml"

pk() { ssh "${PI}" "sudo k3s kubectl --namespace ${NS} $*"; }

load_env() {
  if [ -f "${ENV_FILE}" ]; then
    set -a
    # shellcheck disable=SC1090
    . "${ENV_FILE}"
    set +a
  else
    echo "NOTE: ${ENV_FILE} not found — deploying with auth disabled and no LLM key."
  fi
}

build_ship() {
  docker buildx build --platform linux/arm64 -t "${IMAGE}" --load "${ROOT}"
  echo "Shipping image to the Pi over the direct link..."
  docker save "${IMAGE}" | ssh "${PI}" "sudo k3s ctr images import -"
}

apply_all() {
  ssh "${PI}" "sudo k3s kubectl create namespace ${NS} --dry-run=client -o yaml | sudo k3s kubectl apply -f -"

  ssh "${PI}" "sudo k3s kubectl --namespace ${NS} create secret generic jcmcp-pi-app-secrets \
    --from-literal=entra_tenant_id='${PI_ENTRA_TENANT_ID:-}' \
    --from-literal=entra_client_id='${PI_ENTRA_CLIENT_ID:-}' \
    --from-literal=entra_client_secret='${PI_ENTRA_CLIENT_SECRET:-}' \
    --from-literal=api_key='${PI_API_KEY:-}' \
    --from-literal=llm_provider='${PI_LLM_PROVIDER:-}' \
    --from-literal=llm_api_key='${PI_LLM_API_KEY:-}' \
    --from-literal=oura_client_id='${PI_OURA_CLIENT_ID:-}' \
    --from-literal=oura_client_secret='${PI_OURA_CLIENT_SECRET:-}' \
    --from-literal=app_encryption_key='${PI_APP_ENCRYPTION_KEY:-}' \
    --dry-run=client -o yaml | sudo k3s kubectl apply -f -"

  sed \
    -e "s|__PI_LLM_PROVIDER__|${PI_LLM_PROVIDER:-}|g" \
    -e "s|__PI_FOUNDRY_ENDPOINT__|${PI_FOUNDRY_ENDPOINT:-}|g" \
    -e "s|__PI_FOUNDRY_DEPLOYMENT__|${PI_FOUNDRY_DEPLOYMENT:-}|g" \
    -e "s|__PI_FOUNDRY_API_VERSION__|${PI_FOUNDRY_API_VERSION:-}|g" \
    -e "s|__PI_ENTRA_OWNER_OID__|${PI_ENTRA_OWNER_OID:-}|g" \
    "${K8S_DIR}/configmap.yaml" | ssh "${PI}" "sudo k3s kubectl apply -f -"

  for f in pvc.yaml service.yaml deployment.yaml; do
    ssh "${PI}" "sudo k3s kubectl apply -f -" < "${K8S_DIR}/${f}"
  done

  pk rollout restart deployment/jcmcp-pi
  pk rollout status deployment/jcmcp-pi --timeout=300s
  echo
  echo "jcmcp is up on the Pi:"
  echo "  LAN     http://192.168.68.51/   (dashboard: /dashboard, SPA: /app)"
  echo "  direct  http://192.168.101.2/"
}

case "${1:-}" in
  deploy)
    load_env
    build_ship
    apply_all
    ;;
  apply)
    load_env
    apply_all
    ;;
  kubeconfig)
    mkdir -p "$(dirname "${KUBECONFIG_OUT}")"
    ssh "${PI}" 'sudo cat /etc/rancher/k3s/k3s.yaml' \
      | sed -e 's|https://127.0.0.1:6443|https://192.168.101.2:6443|' \
            -e 's|: default|: pi-node1|' \
      > "${KUBECONFIG_OUT}"
    chmod 600 "${KUBECONFIG_OUT}"
    echo "Wrote ${KUBECONFIG_OUT} — use: kubectl --kubeconfig ${KUBECONFIG_OUT} ..."
    ;;
  status)
    pk get pods,svc,pvc
    ;;
  monitoring)
    ssh "${PI}" "sudo k3s kubectl create namespace monitoring --dry-run=client -o yaml | sudo k3s kubectl apply -f -"
    # Grafana admin secret (out-of-band per grafana.yaml); create once, keep.
    ssh "${PI}" "sudo k3s kubectl -n monitoring get secret grafana-admin >/dev/null 2>&1 || \
      sudo k3s kubectl -n monitoring create secret generic grafana-admin \
        --from-literal=admin-user=admin \
        --from-literal=admin-password=\"\$(openssl rand -base64 18)\""
    # Reuse the AKS manifests verbatim except: Azure storage class → k3s
    # local-path, and scrape the Pi's app namespace.
    sed -e 's/managed-csi/local-path/' \
        -e 's/names: \[jcmcp, jcmcp-qa\]/names: [jcmcp-pi]/' \
        "${ROOT}/k8s/monitoring/prometheus.yaml" | ssh "${PI}" "sudo k3s kubectl apply -f -"
    ssh "${PI}" "sudo k3s kubectl apply -f -" < "${ROOT}/k8s/monitoring/grafana-dashboards.yaml"
    sed -e 's/managed-csi/local-path/' \
        "${ROOT}/k8s/monitoring/grafana.yaml" | ssh "${PI}" "sudo k3s kubectl apply -f -"
    # Expose Grafana on the LAN via ServiceLB (host port 3000).
    ssh "${PI}" "sudo k3s kubectl -n monitoring patch svc grafana -p '{\"spec\":{\"type\":\"LoadBalancer\"}}'"
    ssh "${PI}" "sudo k3s kubectl -n monitoring rollout status deploy/prometheus deploy/grafana --timeout=300s"
    echo
    echo "Grafana:    http://192.168.68.51:3000  (user: admin)"
    echo "Password:   ssh ${PI} \"sudo k3s kubectl -n monitoring get secret grafana-admin -o jsonpath='{.data.admin-password}' | base64 -d\""
    ;;
  logs)
    pk logs -f deployment/jcmcp-pi
    ;;
  backup-setup)
    scp -q "${ROOT}/scripts/pi-backup.sh" "${PI}:/tmp/jcmcp-backup.sh"
    ssh "${PI}" 'set -e
      sudo install -m 755 /tmp/jcmcp-backup.sh /usr/local/bin/jcmcp-backup.sh
      rm /tmp/jcmcp-backup.sh
      printf "[Unit]\nDescription=jcmcp data backup to USB drive\n[Service]\nType=oneshot\nExecStart=/usr/local/bin/jcmcp-backup.sh\n" \
        | sudo tee /etc/systemd/system/jcmcp-backup.service >/dev/null
      printf "[Unit]\nDescription=Nightly jcmcp backup\n[Timer]\nOnCalendar=*-*-* 03:30:00\nPersistent=true\n[Install]\nWantedBy=timers.target\n" \
        | sudo tee /etc/systemd/system/jcmcp-backup.timer >/dev/null
      sudo systemctl daemon-reload
      sudo systemctl enable --now jcmcp-backup.timer
      sudo systemctl list-timers jcmcp-backup.timer --no-pager | head -2'
    echo "Running first backup now..."
    ssh "${PI}" 'sudo /usr/local/bin/jcmcp-backup.sh'
    ;;
  *)
    sed -n '2,12p' "$0"
    exit 1
    ;;
esac
