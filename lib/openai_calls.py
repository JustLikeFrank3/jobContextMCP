"""OpenAI call helpers with usage logging and local rate smoothing."""
from __future__ import annotations

import contextlib
import contextvars
import logging
import threading
import time
from random import SystemRandom
from typing import Any

from lib import metrics

_LOG = logging.getLogger(__name__)

# Per-context sink for token usage, so a caller can attribute spend to the unit
# of work that caused it. Set by lib.work while an executor runs; None
# everywhere else, which makes collection free for every other call site.
#
# A contextvar rather than a parameter threaded through every generator: LLM
# calls happen several frames below the executor, through code paths that have
# no reason to know they're inside a work item. Note this does NOT rely on
# contextvar propagation across an offload (the trap from the 2026-07-09
# incident) — the sink is set inside the thread that runs the executor and read
# in the same frame.
_USAGE_SINK: "contextvars.ContextVar[list | None]" = contextvars.ContextVar(
    "llm_usage_sink", default=None
)


@contextlib.contextmanager
def collect_usage():
    """Collect per-call token usage for the duration of the block.

    Yields the list that accumulates ``{model, prompt, completion}`` entries —
    one per successful call. Nesting is safe: an inner block collects its own
    calls and the outer resumes on exit (the inner's calls are attributed to
    the inner unit of work, which is what you want when one work item spawns
    another).
    """
    entries: list[dict] = []
    token = _USAGE_SINK.set(entries)
    try:
        yield entries
    finally:
        _USAGE_SINK.reset(token)


# Cryptographically-seeded RNG used only for retry-backoff jitter. Avoids the
# non-secure global PRNG so static analysers don't flag it (Sonar S2245 / B311).
_RNG = SystemRandom()
_CHAT_LOCK = threading.Lock()
_LAST_CHAT_CALL = 0.0
_MIN_CHAT_INTERVAL_SECONDS = 12.0


def _error_payload(exc: Exception) -> str:
    """Best-effort raw OpenAI error payload for diagnostics."""
    response = getattr(exc, "response", None)
    if response is not None:
        try:
            text = getattr(response, "text", None)
            if text:
                return str(text)
        except Exception:
            pass
        try:
            return str(response.json())
        except Exception:
            pass
    body = getattr(exc, "body", None)
    if body:
        return str(body)
    return str(exc)


def _retry_after_seconds(exc: Exception, fallback: float) -> float:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", {}) if response is not None else {}
    value = None
    try:
        value = headers.get("retry-after") or headers.get("Retry-After")
    except Exception:
        value = None
    if value:
        try:
            return max(float(value), fallback)
        except ValueError:
            pass
    return fallback


# Sampling knobs that some providers/models reject outright — e.g. Claude
# 4.6+ models behind Anthropic's OpenAI-compat endpoint return 400
# "`temperature` is deprecated for this model.". When a 400 names one of
# these, we drop it and retry: the request is otherwise fine and the model's
# default sampling is what the provider wants us to use anyway.
_DROPPABLE_PARAMS = ("temperature", "top_p", "presence_penalty", "frequency_penalty")

# Quirks learned at runtime, kept for the life of the process so the
# discovery cost (a rejected 400 or an empty-at-cap response) is paid once,
# not on every call — the calibration run paid 3 requests per judge call
# rediscovering the same two claude-sonnet-5 quirks 25 times.
#
# Keyed by endpoint AND model, never model alone: the judge split routinely
# puts the same model name behind two different providers (generator on
# foundry, judge on openai or anthropic), and those endpoints do not accept
# the same params. A quirk observed at one is not evidence about the other,
# so a model-only key would let the judge's discovery silently reshape every
# generator request — the wrong direction for a param the generator needs.
_MODEL_REJECTED_PARAMS: "dict[str, set[str]]" = {}
# Additionally keyed by label. The empty-at-cap floor is a property of the
# prompt as much as the model: an eval_judge call reasons its way through a
# 30KB master resume and needs 8000, while a short summarize call is fine at
# 2000. Keying by model alone let one big call site raise the floor for every
# small one, quietly multiplying their budgets.
_MODEL_MIN_CAP: "dict[tuple[str, str], int]" = {}
_RENAME_MAX_TOKENS = "max_tokens→max_completion_tokens"


def _memory_key(client: Any, kwargs: dict) -> str:
    """Endpoint-qualified model identity for the quirk caches.

    Returns "" when the model is unknown, which disables memory entirely
    rather than lumping every unnamed call under one shared key.
    """
    model = str(kwargs.get("model") or "")
    if not model:
        return ""
    try:
        endpoint = str(getattr(client, "base_url", "") or "")
    except Exception:  # a client whose base_url property raises is not fatal
        endpoint = ""
    return f"{endpoint}|{model}"


def _apply_model_memory(kwargs: dict, key: str, label: str) -> None:
    """Preemptively apply quirks previously learned for this endpoint+model."""
    if not key:
        return
    for param in _MODEL_REJECTED_PARAMS.get(key, ()):
        if param == _RENAME_MAX_TOKENS:
            if "max_tokens" in kwargs:
                kwargs["max_completion_tokens"] = kwargs.pop("max_tokens")
        else:
            kwargs.pop(param, None)
    floor = _MODEL_MIN_CAP.get((key, label), 0)
    if floor:
        for cap_key in ("max_tokens", "max_completion_tokens"):
            if kwargs.get(cap_key) and kwargs[cap_key] < floor:
                kwargs[cap_key] = floor


def _drop_rejected_param(kwargs: dict, payload: str) -> "str | None":
    """Remove the sampling param a 400 payload complains about; return its name."""
    lowered = payload.lower()
    if not any(word in lowered for word in ("deprecated", "unsupported", "not supported", "invalid_request")):
        return None
    for param in _DROPPABLE_PARAMS:
        if param in kwargs and param in lowered:
            kwargs.pop(param)
            return param
    # OpenAI reasoning models reject max_tokens in favor of max_completion_tokens.
    if "max_tokens" in kwargs and "max_completion_tokens" in lowered:
        kwargs["max_completion_tokens"] = kwargs.pop("max_tokens")
        return _RENAME_MAX_TOKENS
    return None


def create_chat_completion(client: Any, *, label: str = "chat", max_attempts: int = 3, **kwargs: Any) -> Any:
    """Create a chat completion with process-local spacing and usage logging.

    Logs requested max_tokens, actual usage, and raw 429 payloads. The lock is
    deliberately process-wide so dashboard-triggered resume/cover/fitment calls
    do not burst into the same rolling TPM/RPM window.
    """
    global _LAST_CHAT_CALL
    memory_key = _memory_key(client, kwargs)
    _apply_model_memory(kwargs, memory_key, label)
    # Collected locally and committed to the shared per-model memory only on
    # eventual success — a 400 whose retry then ALSO fails (wrong diagnosis,
    # or a second unrelated problem) must not permanently poison every future
    # call to this model with a dropped param it never needed dropping.
    learned_rejected: set[str] = set()
    learned_cap = 0
    attempt = 0
    while True:
        attempt += 1
        with _CHAT_LOCK:
            elapsed = time.monotonic() - _LAST_CHAT_CALL
            wait = _MIN_CHAT_INTERVAL_SECONDS - elapsed
            if wait > 0:
                _LOG.info(
                    "openai.chat gate_sleep label=%s wait=%.2fs requested_max_tokens=%s",
                    label,
                    wait,
                    kwargs.get("max_tokens"),
                )
                time.sleep(wait)
            started = time.monotonic()
            try:
                response = client.chat.completions.create(**kwargs)
            except Exception as exc:
                _LAST_CHAT_CALL = time.monotonic()
                status_code = getattr(getattr(exc, "response", None), "status_code", None)
                metrics.inc(
                    "llm_calls_total",
                    label=label,
                    model=str(kwargs.get("model")),
                    outcome=f"error_{status_code or 'network'}",
                )
                payload = _error_payload(exc)
                _LOG.warning(
                    "openai.chat error label=%s attempt=%s status=%s requested_max_tokens=%s payload=%s",
                    label,
                    attempt,
                    status_code,
                    kwargs.get("max_tokens"),
                    payload,
                )
                if status_code == 429 and attempt < max_attempts:
                    backoff = _retry_after_seconds(exc, min(60.0, (2 ** attempt) + _RNG.random()))
                    _LOG.info("openai.chat retry_sleep label=%s wait=%.2fs", label, backoff)
                    time.sleep(backoff)
                    continue
                if status_code == 400 and attempt < max_attempts:
                    dropped = _drop_rejected_param(kwargs, payload)
                    if dropped:
                        learned_rejected.add(dropped)
                        _LOG.info(
                            "openai.chat dropped_param label=%s param=%s (provider rejected it)",
                            label,
                            dropped,
                        )
                        continue
                raise

            _LAST_CHAT_CALL = time.monotonic()
            # Thinking models (Claude 4.6+, OpenAI o-series) count internal
            # reasoning against the completion budget: a too-small max_tokens
            # yields an EMPTY message with the cap fully consumed. Retry once
            # with 4x budget rather than returning nothing.
            choices = getattr(response, "choices", None) or []
            message = getattr(choices[0], "message", None) if choices else None
            content_empty = not getattr(message, "content", None)
            requested_cap = kwargs.get("max_tokens") or kwargs.get("max_completion_tokens")
            used = getattr(getattr(response, "usage", None), "completion_tokens", None)
            if (
                content_empty
                and requested_cap
                and used
                and used >= requested_cap
                and attempt < max_attempts
            ):
                bumped = int(requested_cap) * 4
                key = "max_tokens" if "max_tokens" in kwargs else "max_completion_tokens"
                kwargs[key] = bumped
                learned_cap = max(learned_cap, bumped)
                _LOG.warning(
                    "openai.chat empty_at_cap label=%s cap=%s -> retrying with %s",
                    label, requested_cap, bumped,
                )
                continue
            usage = getattr(response, "usage", None)
            prompt_tokens = getattr(usage, "prompt_tokens", None) if usage else None
            completion_tokens = getattr(usage, "completion_tokens", None) if usage else None
            total_tokens = getattr(usage, "total_tokens", None) if usage else None
            model = str(kwargs.get("model"))
            metrics.inc("llm_calls_total", label=label, model=model, outcome="ok")
            metrics.observe(
                "llm_call_seconds", time.monotonic() - started, label=label, model=model)
            if prompt_tokens:
                metrics.inc("llm_tokens_total", float(prompt_tokens),
                            label=label, model=model, direction="prompt")
            if completion_tokens:
                metrics.inc("llm_tokens_total", float(completion_tokens),
                            label=label, model=model, direction="completion")
            _LOG.info(
                "openai.chat usage label=%s attempt=%s elapsed=%.2fs model=%s requested_max_tokens=%s prompt_tokens=%s completion_tokens=%s total_tokens=%s",
                label,
                attempt,
                time.monotonic() - started,
                kwargs.get("model"),
                kwargs.get("max_tokens"),
                prompt_tokens,
                completion_tokens,
                total_tokens,
            )
            sink = _USAGE_SINK.get()
            if sink is not None:
                sink.append({
                    "model": model,
                    "prompt": int(prompt_tokens or 0),
                    "completion": int(completion_tokens or 0),
                })
            if learned_rejected and memory_key:
                _MODEL_REJECTED_PARAMS.setdefault(memory_key, set()).update(learned_rejected)
            if learned_cap and memory_key:
                cap_key = (memory_key, label)
                _MODEL_MIN_CAP[cap_key] = max(_MODEL_MIN_CAP.get(cap_key, 0), learned_cap)
            return response
