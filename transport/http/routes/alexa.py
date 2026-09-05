"""
Alexa custom-skill webhook — the voice briefing on real Echo hardware.

Alexa+ MCP add-ons are private-preview only (docs/alexa-plus.md), but classic
custom skills remain self-serve: a development-stage skill works on any Echo
signed into the developer account. The skill's HTTPS endpoint POSTs here;
account linking rides the connector key bridge (routes/oauth.py) — the
pitangui/layla callbacks are already allowlisted — so the linked access
token IS a per-user ``jcmcp_`` key.

Security: Alexa cannot send an Authorization header, so this path is public
and every request must prove it came from Alexa before the body is trusted
(developer.amazon.com "Host a Custom Skill as a Web Service"):

1. ``SignatureCertChainUrl`` must be an s3.amazonaws.com/echo.api/ HTTPS URL
   (path-normalized so ``..`` can't escape the prefix).
2. The certificate chain must validate to the system trust store with
   ``echo-api.amazon.com`` in the leaf's SAN.
3. ``Signature-256`` (or legacy SHA-1 ``Signature``) must verify over the
   raw body with the leaf's RSA key.
4. ``request.timestamp`` must be within ±150s (replay window).

Only then is the account-linked key resolved and tenant context established,
mirroring the auth middleware's tenant path.
"""
from __future__ import annotations

import base64
import binascii
import datetime as _dt
import json
import logging
import posixpath
import time
from pathlib import Path
from urllib.parse import urlparse

import certifi
import anyio
import httpx
from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.x509.verification import PolicyBuilder, Store
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from lib import metrics

_logger = logging.getLogger("jobsearch_mcp")

router = APIRouter(tags=["alexa-skill"])

_CERT_HOST = "s3.amazonaws.com"
_CERT_PATH_PREFIX = "/echo.api/"
_LEAF_SAN = "echo-api.amazon.com"
_TIMESTAMP_TOLERANCE_S = 150
_CERT_CACHE_TTL_S = 3600
_CERT_CACHE_MAX = 8

# url -> (leaf_certificate, cached_at). The URL is attacker-influenced but
# pinned to the echo.api bucket path, so the cap is a courtesy, not a defense.
_cert_cache: dict[str, tuple[x509.Certificate, float]] = {}


class AlexaVerificationError(Exception):
    """Request could not be proven to originate from Alexa."""


# ── request verification ───────────────────────────────────────────────────────

def _validate_cert_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise AlexaVerificationError("cert URL must be https")
    if (parsed.hostname or "").lower() != _CERT_HOST:
        raise AlexaVerificationError("cert URL host is not s3.amazonaws.com")
    if parsed.port not in (None, 443):
        raise AlexaVerificationError("cert URL must use port 443")
    if not posixpath.normpath(parsed.path).startswith(_CERT_PATH_PREFIX):
        raise AlexaVerificationError("cert URL path is not under /echo.api/")


def _trust_store() -> Store:
    return Store(
        x509.load_pem_x509_certificates(Path(certifi.where()).read_bytes())
    )


def _verify_chain(certs: list[x509.Certificate]) -> x509.Certificate:
    """Validate the chain to the trust store; return the verified leaf.

    build_server_verifier checks validity windows, the SAN, EKU, and path
    to a trusted root in one pass — the whole checklist Amazon's webhook
    doc spells out, minus the signature over the body.
    """
    if not certs:
        raise AlexaVerificationError("empty certificate chain")
    leaf, *intermediates = certs
    verifier = (
        PolicyBuilder().store(_trust_store()).build_server_verifier(
            x509.DNSName(_LEAF_SAN)
        )
    )
    try:
        verifier.verify(leaf, intermediates)
    except Exception as exc:
        raise AlexaVerificationError(f"certificate chain invalid: {exc}") from exc
    return leaf


async def _verified_signing_cert(url: str) -> x509.Certificate:
    """Validate the cert URL, fetch (cached) and chain-verify, return leaf."""
    _validate_cert_url(url)
    cached = _cert_cache.get(url)
    if cached and time.monotonic() - cached[1] < _CERT_CACHE_TTL_S:
        return cached[0]
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise AlexaVerificationError(f"cert fetch failed: {exc}") from exc
    try:
        certs = x509.load_pem_x509_certificates(resp.content)
    except ValueError as exc:
        raise AlexaVerificationError("cert chain is not valid PEM") from exc
    leaf = _verify_chain(certs)
    if len(_cert_cache) >= _CERT_CACHE_MAX:
        _cert_cache.clear()
    _cert_cache[url] = (leaf, time.monotonic())
    return leaf


def _verify_signature(
    cert: x509.Certificate, signature_b64: str, body: bytes, algorithm: hashes.HashAlgorithm
) -> None:
    try:
        signature = base64.b64decode(signature_b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise AlexaVerificationError("signature is not valid base64") from exc
    try:
        cert.public_key().verify(signature, body, padding.PKCS1v15(), algorithm)
    except InvalidSignature as exc:
        raise AlexaVerificationError("body signature does not verify") from exc


def _verify_timestamp(payload: dict) -> None:
    stamp = (payload.get("request") or {}).get("timestamp", "")
    try:
        then = _dt.datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AlexaVerificationError("unparseable request timestamp") from exc
    if then.tzinfo is None:
        raise AlexaVerificationError("request timestamp is not timezone-aware")
    skew = abs((_dt.datetime.now(_dt.timezone.utc) - then).total_seconds())
    if skew > _TIMESTAMP_TOLERANCE_S:
        raise AlexaVerificationError(f"request timestamp outside ±{_TIMESTAMP_TOLERANCE_S}s")


async def _verify_request(request: Request, raw_body: bytes) -> None:
    cert_url = request.headers.get("signaturecertchainurl", "")
    if not cert_url:
        raise AlexaVerificationError("missing SignatureCertChainUrl header")
    sig_256 = request.headers.get("signature-256", "")
    sig_sha1 = request.headers.get("signature", "")
    if not sig_256 and not sig_sha1:
        raise AlexaVerificationError("missing Signature header")
    cert = await _verified_signing_cert(cert_url)
    if sig_256:
        _verify_signature(cert, sig_256, raw_body, hashes.SHA256())
    else:
        _verify_signature(cert, sig_sha1, raw_body, hashes.SHA1())  # noqa: S303 — Alexa's legacy header


# ── response shapes ────────────────────────────────────────────────────────────

_LINK_SPEECH = (
    "Please open job context in the Alexa app, tap Settings, then Link Account. "
    "After linking, say: Alexa, launch the job context skill."
)
_HELP_SPEECH = (
    "You can ask for your briefing, your application pipeline, or upcoming interviews. "
    "To start again, say: Alexa, launch the job context skill."
)


def _speech(text: str, *, end_session: bool = True, link_account: bool = False,
            view: dict | None = None) -> JSONResponse:
    response: dict = {
        "outputSpeech": {"type": "PlainText", "text": text},
        "shouldEndSession": end_session,
    }
    if link_account:
        response["card"] = {"type": "LinkAccount"}
    if view is not None:
        from transport.http.alexa_views import render_directive

        response["directives"] = [render_directive(view)]
        # Keep the visual session available with the microphone closed.
        response.pop("shouldEndSession")
    elif not end_session:
        response["reprompt"] = {"outputSpeech": {"type": "PlainText", "text": _HELP_SPEECH}}
    return JSONResponse({"version": "1.0", "response": response})


def _linked_oid(payload: dict) -> str | None:
    token = (
        ((payload.get("context") or {}).get("System") or {}).get("user", {})
        or {}
    ).get("accessToken") or (
        ((payload.get("session") or {}).get("user") or {}).get("accessToken")
    )
    if not token or not token.startswith("jcmcp_"):
        return None
    from lib.api_keys import lookup_key

    return lookup_key(token)


def _view_for(oid: str, action: str) -> dict:
    """Run a read-only view inside *oid*'s partition, middleware-style."""
    import lib.config as _cfg_module
    from lib.user_context import (
        reset_data_folder,
        reset_user_oid,
        set_data_folder,
        set_user_oid,
    )
    from lib.user_provisioning import provision_user_data
    from transport.http.alexa_views import build_view

    data_dir = Path(str(_cfg_module.DATA_FOLDER)) / "users" / oid
    provision_user_data(data_dir)
    oid_token = set_user_oid(oid)
    folder_token = set_data_folder(data_dir)
    try:
        return build_view(action)
    finally:
        reset_data_folder(folder_token)
        reset_user_oid(oid_token)


# ── webhook ────────────────────────────────────────────────────────────────────

@router.post("/alexa", include_in_schema=False)
async def alexa_webhook(request: Request) -> JSONResponse:
    raw_body = await request.body()
    try:
        await _verify_request(request, raw_body)
        payload = json.loads(raw_body)
        _verify_timestamp(payload)
    except AlexaVerificationError as exc:
        metrics.inc("alexa_requests_total", result="rejected")
        # Header NAMES only — never values: Authorization or cookie-like
        # headers may carry credentials. Names + UA are enough to tell a
        # classic signed webhook from whatever Alexa+'s pipeline sends.
        _logger.warning(
            "alexa: rejected request (%s) ua=%r headers=%s body_bytes=%d",
            exc,
            request.headers.get("user-agent", ""),
            sorted(request.headers.keys()),
            len(raw_body),
        )
        # Amazon's certification probe expects invalid requests to fail
        # with a non-2xx; 400 is the documented choice.
        return JSONResponse({"error": "invalid_request"}, status_code=400)
    except ValueError:
        metrics.inc("alexa_requests_total", result="rejected")
        return JSONResponse({"error": "invalid_request"}, status_code=400)

    req = payload.get("request") or {}
    req_type = req.get("type", "")

    if req_type == "SessionEndedRequest":
        metrics.inc("alexa_requests_total", result="session_ended")
        return JSONResponse({"version": "1.0", "response": {}})

    if req_type in ("Alexa.Presentation.APL.UserEvent", "Alexa.Presentation.APL.RuntimeError"):
        # No touch actions in this version. Display lifecycle requests must
        # never fall through to a tool or read the user's briefing aloud.
        metrics.inc("alexa_requests_total", result="display_event")
        return JSONResponse({"version": "1.0", "response": {}})

    intent = (req.get("intent") or {}).get("name", "")
    if req_type == "IntentRequest" and intent in ("AMAZON.StopIntent", "AMAZON.CancelIntent"):
        metrics.inc("alexa_requests_total", result="stop")
        return _speech("Goodbye.")
    if req_type == "IntentRequest" and intent in ("AMAZON.HelpIntent", "AMAZON.FallbackIntent"):
        metrics.inc("alexa_requests_total", result="help")
        return _speech(_HELP_SPEECH, end_session=False)

    actions = {"BriefingIntent": "briefing", "PipelineIntent": "pipeline",
               "UpcomingInterviewsIntent": "interviews"}
    action = "briefing" if req_type == "LaunchRequest" else (
        actions.get(intent) if req_type == "IntentRequest" else None)
    if action is None:
        metrics.inc("alexa_requests_total", result="unsupported")
        return _speech(_HELP_SPEECH, end_session=False)

    oid = _linked_oid(payload)
    if not oid:
        metrics.inc("alexa_requests_total", result="unlinked")
        return _speech(_LINK_SPEECH, link_account=True)

    # anyio preserves contextvars; blocking workspace reads must not hold the
    # HTTP event loop and delay health probes or unrelated requests.
    view = await anyio.to_thread.run_sync(_view_for, oid, action)
    interfaces = (((payload.get("context") or {}).get("System") or {}).get("device") or {}).get("supportedInterfaces") or {}
    display = "Alexa.Presentation.APL" in interfaces
    metrics.inc("alexa_requests_total", result="ok")
    return _speech(view["speech"], view=view if display else None)
