#!/usr/bin/env python3
"""Prometheus exporter for the workstation's local-LLM stack (stdlib only).

Serves :9105/metrics for the Pi wallboard's Prometheus (scrape job
``ollama-workstation`` in k8s/monitoring/pi/prometheus-pi.yaml) with three
metric sources merged into one page:

  - The local LLM server, whichever one is running: candidate bases are
    probed via the OpenAI-compatible /v1/models until one answers
    (llama-server :8081 since 2026-08, ollama :11434 kept as a fallback).
    Emits generic local_llm_* series (up, model, context length, model
    file size); llama.cpp additionally gets its native llamacpp:* families
    relayed verbatim from /metrics (its --metrics flag; ollama has no such
    endpoint — 404 as of 0.32.x).
  - GPU via ``nvidia-smi`` (utilization, VRAM, temperature).
  - The desktop app's own llm_* series (calls/tokens/latency for the
    locally served model), relayed. The packaged sidecar binds 127.0.0.1
    on an OS-assigned port, so it is unreachable from the Pi directly; the
    port is rediscovered per scrape from listening sockets owned by
    ``jobcontext-back*`` processes (survives app restarts).

Install with scripts/ollama-exporter-setup.sh (user systemd unit). The
filename and the :9105 port predate the ollama→llama.cpp switch and are
kept on purpose: the systemd unit, the Prometheus job name, and the
dual-boot OS probes (this port answering means the Linux boot is up) all
point here.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 9105
# Probe order is priority: first base whose /v1/models answers wins.
LLM_BASES = (("http://127.0.0.1:8081", "llama.cpp"),
             ("http://127.0.0.1:11434", "ollama"))
TIMEOUT = 3

# Desktop-app families forwarded verbatim (with their # TYPE lines); the
# scrape's job label keeps them distinct from the k8s-scraped series.
RELAY_FAMILIES = ("llm_calls_total", "llm_call_seconds", "llm_tokens_total",
                  "process_uptime_seconds", "provenance_runs_total",
                  "provenance_violations_recorded_total", "eval_")


def _get_json(url: str):
    with urllib.request.urlopen(url, timeout=TIMEOUT) as resp:
        return json.load(resp)


def llm_lines() -> list[str]:
    """Whatever local LLM server is up, found by OpenAI-compatible probe.

    Truthfulness contract (grafana-pi.yaml header): local_llm_up is always
    emitted 0/1 while this exporter is alive, so absent means the exporter
    itself is gone. What a probe cannot observe (context length on a server
    that does not report one) is ABSENT, never 0.
    """
    lines = ["# TYPE local_llm_up gauge"]
    for base, server in LLM_BASES:
        try:
            entries = _get_json(f"{base}/v1/models").get("data", [])
        except Exception:
            continue
        if not entries:
            continue
        model = entries[0].get("id", "unknown")
        size = (entries[0].get("meta") or {}).get("size", 0)
        ftype = ""
        ctx = 0
        try:  # llama.cpp-only detail: served alias, quantization, context
            props = _get_json(f"{base}/props")
            model = props.get("model_alias") or model
            ftype = props.get("model_ftype", "")
            ctx = (props.get("default_generation_settings") or {}).get("n_ctx", 0)
        except Exception:
            pass
        lines += [
            "local_llm_up 1",
            "# TYPE local_llm_info gauge",
            f'local_llm_info{{server="{server}",model="{model}",ftype="{ftype}"}} 1',
        ]
        if ctx:
            lines += ["# TYPE local_llm_context_length gauge",
                      f"local_llm_context_length {ctx}"]
        if size:
            lines += ["# TYPE local_llm_model_size_bytes gauge",
                      f'local_llm_model_size_bytes{{model="{model}"}} {size}']
        # llama.cpp's --metrics page is already Prometheus format; relay it
        # verbatim so rate()/increase() on the Pi see true monotonic series.
        try:
            with urllib.request.urlopen(f"{base}/metrics", timeout=TIMEOUT) as resp:
                body = resp.read().decode()
            lines += [ln for ln in body.splitlines()
                      if ln.startswith(("llamacpp:",
                                        "# TYPE llamacpp:", "# HELP llamacpp:"))]
        except Exception:
            pass
        return lines
    lines.append("local_llm_up 0")
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
    """Sidecar ports found by process-name scan, then any extra fixed ports.

    Order is relay priority (first responder wins per family): the real
    sidecar owns shared families; extras — e.g. a repo-checkout server
    exposing eval_* before a desktop release ships the endpoint, via
    JOBCONTEXT_EXTRA_METRICS_PORTS="8321,8322" — fill in what it lacks.
    """
    ports: list[int] = []
    try:
        out = subprocess.run(["ss", "-ltnHp"], capture_output=True, text=True,
                             timeout=TIMEOUT, check=True).stdout
    except Exception:
        out = ""
    for line in out.splitlines():
        if "jobcontext-back" in line:
            m = re.search(r"127\.0\.0\.1:(\d+)", line)
            if m:
                ports.append(int(m.group(1)))
    for raw in os.environ.get("JOBCONTEXT_EXTRA_METRICS_PORTS", "").split(","):
        raw = raw.strip()
        if raw.isdigit():
            ports.append(int(raw))
    return list(dict.fromkeys(ports))


# Last successful relay, kept so a probe timeout doesn't punch gaps in the
# series: the sidecar's /metrics stalls while an LLM generation blocks its
# event loop — exactly when the wallboard is most interesting.
_relay_cache: list[str] = []


def desktop_lines() -> list[str]:
    ports = _desktop_ports()
    if not ports:
        _relay_cache.clear()
        return ["# TYPE jobcontext_desktop_up gauge", "jobcontext_desktop_up 0"]
    # Merge across ports, first responder wins per family — the frozen
    # sidecar and a repo-checkout server (JOBCONTEXT_EXTRA_METRICS_PORTS)
    # each contribute the families the other lacks, without duplicates.
    collected: list[str] = []
    seen_families: set[str] = set()
    any_ok = False
    for port in ports:
        try:
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/metrics", timeout=TIMEOUT) as resp:
                body = resp.read().decode()
        except Exception:
            continue
        any_ok = True
        port_families: set[str] = set()
        for line in body.splitlines():
            name = line.split("# TYPE ", 1)[-1] if line.startswith("#") else line
            if not name.startswith(RELAY_FAMILIES):
                continue
            family = name.split(" ", 1)[0].split("{", 1)[0]
            if family in seen_families and family not in port_families:
                continue  # an earlier port already owns this family
            port_families.add(family)
            collected.append(line)
        seen_families |= port_families
    if any_ok:
        _relay_cache.clear()
        _relay_cache.extend(collected)
    # Port exists → the app is alive even if the probe timed out (busy
    # generating); serve the cached series rather than dropping them.
    return (["# TYPE jobcontext_desktop_up gauge", "jobcontext_desktop_up 1"]
            + _relay_cache)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 — http.server API
        if self.path != "/metrics":
            self.send_error(404)
            return
        body = "\n".join(llm_lines() + gpu_lines() + desktop_lines()) + "\n"
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
