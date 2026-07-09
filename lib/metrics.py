"""Telemetry P0: an in-process metrics registry with Prometheus exposition.

Counters and duration summaries, thread-safe, zero dependencies — the same
constraint as the control plane (this module ships inside the frozen desktop
sidecar too). The cloud's AKS cluster already runs Azure Monitor's managed
Prometheus agents (ama-metrics); GET /metrics exposes the standard text
format so scraping is a pod-annotation away. Locally it's a debugging page.

What gets instrumented where:
  - HTTP requests   → transport/http/app.py MetricsMiddleware
                      http_requests_total / http_request_seconds{method,route,status}
  - Work items      → lib/work.py dispatcher
                      work_items_total / work_item_seconds{kind,status}
  - LLM calls       → lib/openai_calls.create_chat_completion
                      llm_calls_total{label,model,outcome}
                      llm_call_seconds{label,model}
                      llm_tokens_total{label,model,direction}

Aggregates only — never user content, URLs, or identifiers. Route labels are
route *templates* (/api/work/{item_id}), not raw paths, to bound cardinality.
"""
from __future__ import annotations

import threading
import time

_LabelKey = tuple[str, tuple[tuple[str, str], ...]]

_LOCK = threading.Lock()
_COUNTERS: dict[_LabelKey, float] = {}
_SUMMARIES: dict[_LabelKey, list[float]] = {}  # [count, sum]
_STARTED_AT = time.time()


def _key(name: str, labels: dict[str, str]) -> _LabelKey:
    return name, tuple(sorted((k, str(v)) for k, v in labels.items()))


def inc(name: str, amount: float = 1.0, **labels: str) -> None:
    """Increment a counter."""
    key = _key(name, labels)
    with _LOCK:
        _COUNTERS[key] = _COUNTERS.get(key, 0.0) + amount


def observe(name: str, value: float, **labels: str) -> None:
    """Record one observation into a summary (exposed as _count and _sum)."""
    key = _key(name, labels)
    with _LOCK:
        entry = _SUMMARIES.setdefault(key, [0.0, 0.0])
        entry[0] += 1
        entry[1] += value


def snapshot() -> dict:
    """Plain-dict view for tests and debugging: one entry per label set."""
    with _LOCK:
        counters = [
            {"name": name, "labels": dict(labels), "value": v}
            for (name, labels), v in sorted(_COUNTERS.items())
        ]
        summaries = [
            {"name": name, "labels": dict(labels), "count": e[0], "sum": e[1]}
            for (name, labels), e in sorted(_SUMMARIES.items())
        ]
    return {"counters": counters, "summaries": summaries}


def reset() -> None:
    """Test hook: clear all series."""
    with _LOCK:
        _COUNTERS.clear()
        _SUMMARIES.clear()


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _fmt_labels(labels: tuple[tuple[str, str], ...]) -> str:
    if not labels:
        return ""
    inner = ",".join(f'{k}="{_escape(v)}"' for k, v in labels)
    return "{" + inner + "}"


def render_prometheus() -> str:
    """Render every series in the Prometheus text exposition format."""
    lines: list[str] = [
        "# TYPE process_uptime_seconds gauge",
        f"process_uptime_seconds {time.time() - _STARTED_AT:.1f}",
    ]
    with _LOCK:
        counter_names = sorted({name for name, _ in _COUNTERS})
        for name in counter_names:
            lines.append(f"# TYPE {name} counter")
            for (n, labels), value in sorted(_COUNTERS.items()):
                if n == name:
                    lines.append(f"{name}{_fmt_labels(labels)} {value:g}")
        summary_names = sorted({name for name, _ in _SUMMARIES})
        for name in summary_names:
            lines.append(f"# TYPE {name} summary")
            for (n, labels), (count, total) in sorted(_SUMMARIES.items()):
                if n == name:
                    lines.append(f"{name}_count{_fmt_labels(labels)} {count:g}")
                    lines.append(f"{name}_sum{_fmt_labels(labels)} {total:g}")
    return "\n".join(lines) + "\n"


class timed:  # noqa: N801 — context manager reads like a keyword
    """Measure a block and record it: ``with metrics.timed("x_seconds", k=v): ...``

    The ``outcome`` label is added automatically ("ok" or "error" by whether
    the block raised) unless the caller supplied one.
    """

    def __init__(self, name: str, **labels: str) -> None:
        self._name = name
        self._labels = labels
        self._start = 0.0

    def __enter__(self) -> "timed":
        self._start = time.monotonic()
        return self

    def __exit__(self, exc_type, _exc, _tb) -> None:
        labels = dict(self._labels)
        labels.setdefault("outcome", "error" if exc_type else "ok")
        observe(self._name, time.monotonic() - self._start, **labels)
