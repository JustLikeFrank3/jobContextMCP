#!/usr/bin/env python3
"""Prometheus exporter for the workstation's local-LLM stack (stdlib only).

Serves :9105/metrics for the Pi wallboard's Prometheus (scrape job
``ollama-workstation`` in k8s/monitoring/pi/prometheus-pi.yaml) with three
metric sources merged into one page:

  - Ollama (localhost:11434): up/version plus per-loaded-model size, VRAM
    and context length via /api/ps. Ollama has no native /metrics endpoint
    (404 as of 0.32.x) — this is the workaround.
  - GPU via ``nvidia-smi`` (utilization, VRAM, temperature).
  - The desktop app's own llm_* series (calls/tokens/latency for the
    ollama-served model), relayed. The packaged sidecar binds 127.0.0.1 on
    an OS-assigned port, so it is unreachable from the Pi directly; the
    port is rediscovered per scrape from listening sockets owned by
    ``jobcontext-back*`` processes (survives app restarts).

Install with scripts/ollama-exporter-setup.sh (user systemd unit).
"""
from __future__ import annotations

import json
import re
import subprocess
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 9105
OLLAMA = "http://127.0.0.1:11434"
TIMEOUT = 3

# Desktop-app families forwarded verbatim (with their # TYPE lines); the
# scrape's job label keeps them distinct from the k8s-scraped series.
RELAY_FAMILIES = ("llm_calls_total", "llm_call_seconds", "llm_tokens_total",
                  "process_uptime_seconds")


def _get_json(url: str):
    with urllib.request.urlopen(url, timeout=TIMEOUT) as resp:
        return json.load(resp)


def ollama_lines() -> list[str]:
    lines = ["# TYPE ollama_up gauge"]
    try:
        version = _get_json(f"{OLLAMA}/api/version").get("version", "unknown")
        loaded = _get_json(f"{OLLAMA}/api/ps").get("models", [])
    except Exception:
        lines.append("ollama_up 0")
        return lines
    lines += [
        "ollama_up 1",
        "# TYPE ollama_info gauge",
        f'ollama_info{{version="{version}"}} 1',
        "# TYPE ollama_model_size_bytes gauge",
        "# TYPE ollama_model_size_vram_bytes gauge",
        "# TYPE ollama_model_context_length gauge",
    ]
    for m in loaded:
        name = m.get("name", "unknown")
        details = m.get("details", {})
        info = (f'model="{name}"'
                f',parameter_size="{details.get("parameter_size", "")}"'
                f',quantization="{details.get("quantization_level", "")}"')
        lines += [
            f'ollama_model_size_bytes{{model="{name}"}} {m.get("size", 0)}',
            f'ollama_model_size_vram_bytes{{model="{name}"}} {m.get("size_vram", 0)}',
            f'ollama_model_context_length{{model="{name}"}} {m.get("context_length", 0)}',
            "# TYPE ollama_model_info gauge",
            f"ollama_model_info{{{info}}} 1",
        ]
    return lines


def gpu_lines() -> list[str]:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=TIMEOUT, check=True,
        ).stdout.strip().splitlines()
    except Exception:
        return []
    lines = [
        "# TYPE gpu_utilization_percent gauge",
        "# TYPE gpu_memory_used_bytes gauge",
        "# TYPE gpu_memory_total_bytes gauge",
        "# TYPE gpu_temperature_celsius gauge",
    ]
    for idx, row in enumerate(out):
        util, mem_used, mem_total, temp = (v.strip() for v in row.split(","))
        gpu = f'gpu="{idx}"'
        lines += [
            f"gpu_utilization_percent{{{gpu}}} {util}",
            f"gpu_memory_used_bytes{{{gpu}}} {float(mem_used) * 1048576:.0f}",
            f"gpu_memory_total_bytes{{{gpu}}} {float(mem_total) * 1048576:.0f}",
            f"gpu_temperature_celsius{{{gpu}}} {temp}",
        ]
    return lines


def _desktop_ports() -> list[int]:
    try:
        out = subprocess.run(["ss", "-ltnHp"], capture_output=True, text=True,
                             timeout=TIMEOUT, check=True).stdout
    except Exception:
        return []
    ports = []
    for line in out.splitlines():
        if "jobcontext-back" in line:
            m = re.search(r"127\.0\.0\.1:(\d+)", line)
            if m:
                ports.append(int(m.group(1)))
    return sorted(set(ports))


def desktop_lines() -> list[str]:
    for port in _desktop_ports():
        try:
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/metrics", timeout=TIMEOUT) as resp:
                body = resp.read().decode()
        except Exception:
            continue
        lines = ["# TYPE jobcontext_desktop_up gauge", "jobcontext_desktop_up 1"]
        for line in body.splitlines():
            name = line.split("# TYPE ", 1)[-1] if line.startswith("#") else line
            if name.startswith(RELAY_FAMILIES):
                lines.append(line)
        return lines
    return ["# TYPE jobcontext_desktop_up gauge", "jobcontext_desktop_up 0"]


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 — http.server API
        if self.path != "/metrics":
            self.send_error(404)
            return
        body = "\n".join(ollama_lines() + gpu_lines() + desktop_lines()) + "\n"
        payload = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):  # quiet — systemd journal doesn't need per-scrape noise
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
