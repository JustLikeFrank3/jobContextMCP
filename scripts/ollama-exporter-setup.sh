#!/usr/bin/env bash
# ollama-exporter-setup.sh — install scripts/ollama-exporter.py as a user
# systemd service on the workstation (no root needed; port 9105 is
# unprivileged). The Pi wallboard's Prometheus scrapes it at
# <workstation-LAN-IP>:9105 (job ollama-workstation in
# k8s/monitoring/pi/prometheus-pi.yaml).
#
# Lingering is enabled so the exporter runs even before login after a
# reboot; if `loginctl enable-linger` needs auth on this box, run it once
# manually with sudo.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UNIT_DIR="${HOME}/.config/systemd/user"

mkdir -p "${UNIT_DIR}"
cat > "${UNIT_DIR}/ollama-exporter.service" <<EOF
[Unit]
Description=Prometheus exporter for Ollama + GPU + jobContext desktop metrics

[Service]
ExecStart=/usr/bin/python3 ${ROOT}/scripts/ollama-exporter.py
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now ollama-exporter.service
loginctl enable-linger "${USER}" 2>/dev/null \
  || echo "NOTE: enable-linger needs auth here — run: sudo loginctl enable-linger ${USER}"

sleep 1
curl -sf "http://localhost:9105/metrics" | head -5
echo "ollama-exporter is up on :9105"
