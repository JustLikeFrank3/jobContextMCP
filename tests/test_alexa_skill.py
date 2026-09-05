"""Alexa custom-skill webhook (/alexa): origin proof, then tenant-scoped speech.

The route is public (Alexa cannot send an Authorization header), so the
contract under test is layered:

- SignatureCertChainUrl must be pinned to https://s3.amazonaws.com/echo.api/
  (normalized path — no ``..`` escapes, no odd ports, no lookalike hosts)
- the body signature must verify against the chain's leaf cert (SHA-256
  preferred, legacy SHA-1 accepted); a self-signed chain must NOT verify
- request.timestamp outside the ±150s replay window is rejected with 400
- the account-linked accessToken is a jcmcp_ key: missing/unknown keys get
  a LinkAccount card, a valid key runs the briefing inside that user's
  partition (contextvars set exactly like the auth middleware)
- Stop/Cancel/Help/SessionEnded speak their fixed shapes
"""
from __future__ import annotations

import base64
import datetime as _dt
import json
import sqlite3
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import NameOID

from transport.http.routes import alexa

_CERT_URL = "https://s3.amazonaws.com/echo.api/echo-api-cert-12.pem"


# ── crypto fixtures ────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def signing_pair():
    """Self-signed cert with Alexa's SAN + its private key."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "echo-api.amazon.com")])
    now = _dt.datetime.now(_dt.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - _dt.timedelta(days=1))
        .not_valid_after(now + _dt.timedelta(days=365))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName("echo-api.amazon.com")]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    return key, cert


def _fresh_payload(**overrides) -> dict:
    payload = {
        "version": "1.0",
        "session": {"user": {}},
        "context": {"System": {"user": {}}},
        "request": {
            "type": "LaunchRequest",
            "requestId": "amzn1.echo-api.request.test",
            "timestamp": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
    }
    for key, value in overrides.items():
        payload[key] = value
    return payload


def _with_token(payload: dict, token: str) -> dict:
    payload["context"]["System"]["user"]["accessToken"] = token
    return payload


# ── unit: cert URL pinning ─────────────────────────────────────────────────────

class TestCertUrl:
    def test_canonical_url_accepted(self):
        alexa._validate_cert_url(_CERT_URL)

    def test_explicit_443_accepted(self):
        alexa._validate_cert_url(
            "https://s3.amazonaws.com:443/echo.api/echo-api-cert.pem"
        )

    @pytest.mark.parametrize(
        "url",
        [
            "http://s3.amazonaws.com/echo.api/cert.pem",  # not https
            "https://notamazon.example.com/echo.api/cert.pem",  # wrong host
            "https://s3.amazonaws.com.evil.example/echo.api/cert.pem",  # lookalike
            "https://s3.amazonaws.com:8443/echo.api/cert.pem",  # odd port
            "https://s3.amazonaws.com/EcHo.aPi/cert.pem",  # case-mangled path
            "https://s3.amazonaws.com/bucket/cert.pem",  # wrong path
            "https://s3.amazonaws.com/echo.api/../bucket/cert.pem",  # traversal
            "",  # empty
        ],
    )
    def test_bad_urls_rejected(self, url):
        with pytest.raises(alexa.AlexaVerificationError):
            alexa._validate_cert_url(url)


# ── unit: timestamp window ─────────────────────────────────────────────────────

class TestTimestamp:
    def test_fresh_timestamp_accepted(self):
        alexa._verify_timestamp(_fresh_payload())

    def test_stale_timestamp_rejected(self):
        stale = (
            _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(seconds=301)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        payload = _fresh_payload()
        payload["request"]["timestamp"] = stale
        with pytest.raises(alexa.AlexaVerificationError):
            alexa._verify_timestamp(payload)

    def test_naive_timestamp_rejected(self):
        payload = _fresh_payload()
        payload["request"]["timestamp"] = "2026-01-01T00:00:00"
        with pytest.raises(alexa.AlexaVerificationError):
            alexa._verify_timestamp(payload)

    def test_garbage_timestamp_rejected(self):
        payload = _fresh_payload()
        payload["request"]["timestamp"] = "not-a-date"
        with pytest.raises(alexa.AlexaVerificationError):
            alexa._verify_timestamp(payload)


# ── unit: body signature ───────────────────────────────────────────────────────

class TestSignature:
    def test_valid_sha256_signature(self, signing_pair):
        key, cert = signing_pair
        body = b'{"hello": "echo"}'
        sig = base64.b64encode(
            key.sign(body, padding.PKCS1v15(), hashes.SHA256())
        ).decode()
        alexa._verify_signature(cert, sig, body, hashes.SHA256())

    def test_tampered_body_rejected(self, signing_pair):
        key, cert = signing_pair
        sig = base64.b64encode(
            key.sign(b"original", padding.PKCS1v15(), hashes.SHA256())
        ).decode()
        with pytest.raises(alexa.AlexaVerificationError):
            alexa._verify_signature(cert, sig, b"tampered", hashes.SHA256())

    def test_invalid_base64_rejected(self, signing_pair):
        _, cert = signing_pair
        with pytest.raises(alexa.AlexaVerificationError):
            alexa._verify_signature(cert, "!!not-base64!!", b"x", hashes.SHA256())


# ── unit: chain trust ──────────────────────────────────────────────────────────

class TestChainTrust:
    def test_self_signed_chain_is_untrusted(self, signing_pair):
        # A cert with the right SAN but no path to a real trust root must
        # fail — this is what stops an attacker hosting a lookalike cert.
        _, cert = signing_pair
        with pytest.raises(alexa.AlexaVerificationError):
            alexa._verify_chain([cert])

    def test_empty_chain_rejected(self):
        with pytest.raises(alexa.AlexaVerificationError):
            alexa._verify_chain([])


# ── unit: cert fetch + cache ───────────────────────────────────────────────────

class TestCertFetch:
    @pytest.fixture()
    def fetch_env(self, monkeypatch, signing_pair):
        _, cert = signing_pair
        pem = cert.public_bytes(serialization.Encoding.PEM)
        calls = {"n": 0}

        class _Resp:
            content = pem

            def raise_for_status(self):
                pass

        class _Client:
            def __init__(self, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def get(self, url):
                calls["n"] += 1
                return _Resp()

        monkeypatch.setattr(alexa.httpx, "AsyncClient", _Client)
        # Chain trust is unit-tested separately; identity here isolates the
        # fetch/cache behavior.
        monkeypatch.setattr(alexa, "_verify_chain", lambda certs: certs[0])
        alexa._cert_cache.clear()
        yield cert, calls
        alexa._cert_cache.clear()

    def test_fetches_parses_and_caches(self, fetch_env):
        import asyncio

        cert, calls = fetch_env
        first = asyncio.run(alexa._verified_signing_cert(_CERT_URL))
        second = asyncio.run(alexa._verified_signing_cert(_CERT_URL))
        assert first == cert and second == cert
        assert calls["n"] == 1, "second hit must come from the cache"

    def test_non_pem_body_rejected(self, fetch_env, monkeypatch):
        import asyncio

        class _BadResp:
            content = b"this is not PEM"

            def raise_for_status(self):
                pass

        class _BadClient:
            def __init__(self, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def get(self, url):
                return _BadResp()

        monkeypatch.setattr(alexa.httpx, "AsyncClient", _BadClient)
        with pytest.raises(alexa.AlexaVerificationError):
            asyncio.run(alexa._verified_signing_cert(_CERT_URL))


# ── webhook end-to-end (chain fetch stubbed, signatures real) ─────────────────

@pytest.fixture()
def alexa_client(monkeypatch, isolated_server, tmp_path, signing_pair):
    """TestClient with the cert fetch+chain step pinned to the test cert.

    URL pinning and chain trust are unit-tested above; here they are
    replaced so the signature/timestamp/token/tenant layers run for real.
    """
    from scripts.migrate_to_sqlite import _SCHEMA
    import lib.db as _db

    db_file = tmp_path / "alexa-global.db"
    con = sqlite3.connect(db_file)
    con.executescript(_SCHEMA)
    con.commit()
    con.close()
    monkeypatch.setattr(_db, "global_db_path", lambda: db_file)
    monkeypatch.setattr(_db, "db_path", lambda: db_file)

    monkeypatch.delenv("ENTRA_TENANT_ID", raising=False)
    monkeypatch.delenv("ENTRA_CLIENT_ID", raising=False)
    monkeypatch.delenv("API_KEY", raising=False)

    _, cert = signing_pair

    async def _pinned_cert(url: str) -> x509.Certificate:
        alexa._validate_cert_url(url)  # keep the URL layer live
        return cert

    monkeypatch.setattr(alexa, "_verified_signing_cert", _pinned_cert)

    from fastapi.testclient import TestClient
    from transport.http.app import create_app
    from transport.http.config import reset_settings_cache
    from transport.http.security import reset_auth_provider_cache

    reset_settings_cache()
    reset_auth_provider_cache()
    app = create_app()
    with TestClient(app) as client:
        yield client
    reset_settings_cache()
    reset_auth_provider_cache()


def _post_signed(client, payload: dict, key, *, sha1: bool = False, mangle_sig: bool = False):
    body = json.dumps(payload).encode()
    algo = hashes.SHA1() if sha1 else hashes.SHA256()
    sig = base64.b64encode(key.sign(body, padding.PKCS1v15(), algo)).decode()
    if mangle_sig:
        sig = base64.b64encode(b"\x00" * 256).decode()
    headers = {
        "SignatureCertChainUrl": _CERT_URL,
        "Content-Type": "application/json",
        ("Signature" if sha1 else "Signature-256"): sig,
    }
    return client.post("/alexa", content=body, headers=headers)


class TestWebhook:
    def _linked_key(self, oid: str = "oid-echo") -> str:
        from lib.api_keys import create_key

        _, plaintext = create_key(oid, "Alexa+ connector")
        return plaintext

    def test_launch_speaks_briefing_in_users_partition(
        self, alexa_client, monkeypatch, signing_pair
    ):
        key, _ = signing_pair
        seen = {}

        def _fake_briefing():
            from lib.user_context import get_current_user_oid, get_data_folder_override

            seen["oid"] = get_current_user_oid()
            seen["folder"] = str(get_data_folder_override())
            return "Two interviews this week."

        from tools import digest

        monkeypatch.setattr(digest, "get_voice_briefing", _fake_briefing)

        token = self._linked_key("oid-echo")
        resp = _post_signed(
            alexa_client, _with_token(_fresh_payload(), token), key
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["response"]["outputSpeech"]["text"] == "Two interviews this week."
        assert body["response"]["shouldEndSession"] is True
        assert seen["oid"] == "oid-echo"
        assert Path(seen["folder"]).parts[-2:] == ("users", "oid-echo")
        assert "directives" not in body["response"]

    def test_legacy_sha1_signature_accepted(
        self, alexa_client, monkeypatch, signing_pair
    ):
        key, _ = signing_pair
        from tools import digest

        monkeypatch.setattr(digest, "get_voice_briefing", lambda: "Hello.")
        token = self._linked_key()
        resp = _post_signed(
            alexa_client, _with_token(_fresh_payload(), token), key, sha1=True
        )
        assert resp.status_code == 200

    def test_missing_token_gets_link_account_card(self, alexa_client, signing_pair):
        key, _ = signing_pair
        resp = _post_signed(alexa_client, _fresh_payload(), key)
        assert resp.status_code == 200
        response = resp.json()["response"]
        assert response["card"] == {"type": "LinkAccount"}
        assert "link" in response["outputSpeech"]["text"].lower()

    def test_unknown_key_gets_link_account_card(self, alexa_client, signing_pair):
        key, _ = signing_pair
        payload = _with_token(_fresh_payload(), "jcmcp_" + "x" * 32)
        resp = _post_signed(alexa_client, payload, key)
        assert resp.json()["response"]["card"] == {"type": "LinkAccount"}

    def test_stop_intent_says_goodbye(self, alexa_client, signing_pair):
        key, _ = signing_pair
        payload = _fresh_payload()
        payload["request"]["type"] = "IntentRequest"
        payload["request"]["intent"] = {"name": "AMAZON.StopIntent"}
        resp = _post_signed(alexa_client, payload, key)
        assert resp.json()["response"]["outputSpeech"]["text"] == "Goodbye."

    def test_help_intent_keeps_session_open(self, alexa_client, signing_pair):
        key, _ = signing_pair
        payload = _fresh_payload()
        payload["request"]["type"] = "IntentRequest"
        payload["request"]["intent"] = {"name": "AMAZON.HelpIntent"}
        resp = _post_signed(alexa_client, payload, key)
        assert resp.json()["response"]["shouldEndSession"] is False

    def test_session_ended_returns_empty_response(self, alexa_client, signing_pair):
        key, _ = signing_pair
        payload = _fresh_payload()
        payload["request"]["type"] = "SessionEndedRequest"
        resp = _post_signed(alexa_client, payload, key)
        assert resp.status_code == 200
        assert resp.json()["response"] == {}

    def test_bad_signature_rejected_400(self, alexa_client, signing_pair):
        key, _ = signing_pair
        resp = _post_signed(alexa_client, _fresh_payload(), key, mangle_sig=True)
        assert resp.status_code == 400

    def test_stale_timestamp_rejected_400(self, alexa_client, signing_pair):
        key, _ = signing_pair
        payload = _fresh_payload()
        payload["request"]["timestamp"] = "2020-01-01T00:00:00Z"
        resp = _post_signed(alexa_client, payload, key)
        assert resp.status_code == 400

    def test_missing_signature_headers_rejected_400(self, alexa_client):
        resp = alexa_client.post(
            "/alexa", content=b"{}", headers={"Content-Type": "application/json"}
        )
        assert resp.status_code == 400

    def test_reachable_without_authorization_header(self, alexa_client):
        # Public-prefix regression guard: the middleware must not 401/503
        # or redirect this path; the route's own 400 proves it was reached.
        resp = alexa_client.post(
            "/alexa", content=b"{}", headers={"Content-Type": "application/json"}
        )
        assert resp.status_code == 400

    @pytest.mark.parametrize("intent,action", [("PipelineIntent", "pipeline"),
                                              ("UpcomingInterviewsIntent", "interviews")])
    def test_view_dispatch_keeps_tenant_context(self, alexa_client, signing_pair, monkeypatch, intent, action):
        from lib.user_context import get_current_user_oid, get_data_folder_override
        from transport.http import alexa_views

        def view(requested):
            assert requested == action
            assert get_current_user_oid() == "oid-show"
            assert get_data_folder_override().parts[-2:] == ("users", "oid-show")
            return {"title": "Test", "summary": "Safe summary", "speech": "Safe summary", "rows": []}

        monkeypatch.setattr(alexa_views, "build_view", view)
        payload = _with_token(_fresh_payload(), self._linked_key("oid-show"))
        payload["request"].update(type="IntentRequest", intent={"name": intent})
        payload["context"]["System"]["device"] = {"supportedInterfaces": {"Alexa.Presentation.APL": {}}}
        response = _post_signed(alexa_client, payload, signing_pair[0]).json()["response"]
        assert response["outputSpeech"]["text"] == "Safe summary"
        assert "shouldEndSession" not in response
        assert response["directives"][0]["type"] == "Alexa.Presentation.APL.RenderDocument"
        assert get_current_user_oid() != "oid-show"

    @pytest.mark.parametrize("kind,intent", [("IntentRequest", "DeleteEverythingIntent"),
                                             ("Alexa.Presentation.APL.UserEvent", ""),
                                             ("Alexa.Presentation.APL.RuntimeError", "")])
    def test_unknown_and_display_events_never_read_workspace(self, alexa_client, signing_pair, monkeypatch, kind, intent):
        def forbidden(*args):
            pytest.fail("unexpected workspace read")
        monkeypatch.setattr(alexa, "_view_for", forbidden)
        payload = _fresh_payload()
        payload["request"].update(type=kind, intent={"name": intent})
        assert _post_signed(alexa_client, payload, signing_pair[0]).status_code == 200

    def test_unlinked_show_never_receives_workspace_visuals(self, alexa_client, signing_pair):
        payload = _fresh_payload()
        payload["context"]["System"]["device"] = {"supportedInterfaces": {"Alexa.Presentation.APL": {}}}
        response = _post_signed(alexa_client, payload, signing_pair[0]).json()["response"]
        assert response["card"]["type"] == "LinkAccount"
        assert "directives" not in response
