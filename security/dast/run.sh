#!/usr/bin/env bash
# No target argument or environment override: active scans are disposable only.
set -euo pipefail
[[ $# == 0 ]] || { echo 'This scan does not accept targets or arguments' >&2; exit 1; }
cd "$(dirname "$0")/../.."
readonly ZAP_IMAGE='ghcr.io/zaproxy/zaproxy@sha256:5ccfff9a411743ab2615136a2edd7416bec9ce41572fa94e935df38c14adb2b6'
readonly PREFIX="jobcontext-dast-$$"
readonly NETWORK="$PREFIX-network"
readonly APP="$PREFIX-app"
readonly SCANNER="$PREFIX-zap"
readonly IMAGE="$PREFIX:local"
mkdir -p security/dast/reports
# Never let a failed repeat run reuse a previous scan's successful report.
rm -f security/dast/reports/{report.json,report.html,report.md,app.log}
# ZAP's unprivileged container user must be able to write the mounted reports.
chmod 777 security/dast/reports
cleanup() {
  docker logs "$APP" > security/dast/reports/app.log 2>&1 || true
  docker rm -f "$SCANNER" "$APP" >/dev/null 2>&1 || true
  docker network rm "$NETWORK" >/dev/null 2>&1 || true
  docker image rm "$IMAGE" >/dev/null 2>&1 || true
}
trap cleanup EXIT
# Pull/build before isolation; no secrets, credentials or personal data passed.
docker pull "$ZAP_IMAGE"
docker build -f security/dast/Dockerfile -t "$IMAGE" .
docker network create --internal "$NETWORK"
docker run -d --name "$APP" --network "$NETWORK" --network-alias app \
  --read-only --cap-drop ALL --security-opt no-new-privileges \
  --tmpfs /sandbox:rw,nosuid,nodev,uid=10001,gid=10001,mode=700 \
  --tmpfs /tmp:rw,nosuid,nodev --memory 2g --cpus 2 "$IMAGE"
ready=false
for attempt in $(seq 1 60); do
  if docker exec "$APP" python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"; then
    ready=true; break
  fi
  sleep 2
done
[[ "$ready" == true ]] || { echo 'Disposable app never became healthy' >&2; exit 1; }
set +e
timeout 20m docker run --name "$SCANNER" --network "$NETWORK" \
  --cap-drop ALL --security-opt no-new-privileges --memory 3g --cpus 2 \
  -v "$PWD/security/dast/reports:/zap/wrk:rw" "$ZAP_IMAGE" \
  zap-full-scan.py -t http://app:8000 -m 2 -T 5 \
  -J report.json -r report.html -w report.md
status=$?
set -e
# ZAP codes 1/2 mean findings; severity is enforced below. Errors/timeouts fail.
if (( status > 2 )); then
  echo "ZAP execution failed (exit $status)" >&2; exit "$status"
fi
python3 security/dast/check_report.py security/dast/reports/report.json
