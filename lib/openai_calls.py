"""OpenAI call helpers with usage logging and local rate smoothing."""
from __future__ import annotations

import logging
import threading
import time
from random import SystemRandom
from typing import Any

_LOG = logging.getLogger(__name__)
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
        return "max_tokens→max_completion_tokens"
    return None


def create_chat_completion(client: Any, *, label: str = "chat", max_attempts: int = 3, **kwargs: Any) -> Any:
    """Create a chat completion with process-local spacing and usage logging.

    Logs requested max_tokens, actual usage, and raw 429 payloads. The lock is
    deliberately process-wide so dashboard-triggered resume/cover/fitment calls
    do not burst into the same rolling TPM/RPM window.
    """
    global _LAST_CHAT_CALL
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
                        _LOG.info(
                            "openai.chat dropped_param label=%s param=%s (provider rejected it)",
                            label,
                            dropped,
                        )
                        continue
                raise

            _LAST_CHAT_CALL = time.monotonic()
            usage = getattr(response, "usage", None)
            prompt_tokens = getattr(usage, "prompt_tokens", None) if usage else None
            completion_tokens = getattr(usage, "completion_tokens", None) if usage else None
            total_tokens = getattr(usage, "total_tokens", None) if usage else None
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
            return response
