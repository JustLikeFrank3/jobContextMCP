"""Regressions for the hosted-connector reconnect bug (2026-08-01).

Three deploys in one session each dropped the app.jobcontext.ai MCP connector
and required a manual reconnect. Two independent defects caused it:

  1. The MCP Streamable HTTP transport ran in session mode. Sessions live in
     a process-local dict with no event store, so a pod replacement (deploys
     are replicas=1 + Recreate) destroyed every session and the next request
     carrying the old Mcp-Session-Id got a 404 with no recovery path.

  2. A failure to REACH Entra's JWKS endpoint was indistinguishable from a
     token that had been checked and found invalid — both returned None from
     authenticate_request, which the middleware turned into 401 + a
     WWW-Authenticate challenge. That tells a client its credential is dead.

These tests pin both fixes plus the readiness gate that keeps traffic off a
pod that cannot yet verify signatures.
"""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from jwt.exceptions import PyJWKClientConnectionError

from transport.http.app import create_app
from transport.http.config import reset_settings_cache
from transport.http.security import (
    AuthUnavailable,
    EntraAuthProvider,
    reset_auth_provider_cache,
)


# ===========================================================================
# 1. MCP transport must be stateless — there must be no session to lose
# ===========================================================================

class TestStatelessTransport:
    def test_server_configures_stateless_http(self):
        """The FastMCP instance must run stateless.

        If this flips back to session mode, every deploy again strands live
        connectors on a session id the new pod has never heard of.
        """
        import server as _server

        assert _server.mcp.settings.stateless_http is True

    def test_session_manager_is_stateless(self):
        """The SDK session manager built from those settings must agree."""
        import server as _server

        _server.mcp.streamable_http_app()
        assert _server.mcp.session_manager.stateless is True

    def test_stateless_manager_keeps_no_session_registry(self):
        """Stateless mode must not accumulate per-session transports."""
        import server as _server

        _server.mcp.streamable_http_app()
        assert _server.mcp.session_manager._server_instances == {}


# ===========================================================================
# 2. "Cannot verify" must not be reported as "invalid credential"
# ===========================================================================

class TestUnverifiableCredential:
    def test_jwks_unreachable_raises_auth_unavailable(self):
        """A network failure reaching Entra is not a verdict on the token."""
        provider = EntraAuthProvider()
        with patch(
            "lib.auth.validate_token",
            side_effect=PyJWKClientConnectionError("connection refused"),
        ):
            with pytest.raises(AuthUnavailable):
                provider.authenticate_request("Bearer some-token", None)

    def test_unexpected_error_raises_auth_unavailable(self):
        """An unexpected failure is also not a verdict — fail retryable."""
        provider = EntraAuthProvider()
        with patch("lib.auth.validate_token", side_effect=RuntimeError("boom")):
            with pytest.raises(AuthUnavailable):
                provider.authenticate_request("Bearer some-token", None)

    def test_genuinely_invalid_token_still_returns_none(self):
        """A token that WAS checked and failed must still be rejected."""
        import jwt

        provider = EntraAuthProvider()
        with patch(
            "lib.auth.validate_token",
            side_effect=jwt.InvalidSignatureError("bad signature"),
        ):
            assert provider.authenticate_request("Bearer bad-token", None) is None

    def test_expired_token_still_returns_none(self):
        import jwt

        provider = EntraAuthProvider()
        with patch(
            "lib.auth.validate_token", side_effect=jwt.ExpiredSignatureError("expired")
        ):
            assert provider.authenticate_request("Bearer old-token", None) is None


# ===========================================================================
# 3. The middleware must translate that distinction into the right status
# ===========================================================================

class _RaisingProvider:
    """Provider whose backing key store is unreachable."""

    auth_enabled = True

    def authenticate_request(self, authorization, session_token):
        raise AuthUnavailable("jwks unreachable")

    def authenticate_login(self, credential):
        return None


class _RejectingProvider:
    """Provider that checked the credential and rejected it."""

    auth_enabled = True

    def authenticate_request(self, authorization, session_token):
        return None

    def authenticate_login(self, credential):
        return None


def _client_with_provider(monkeypatch, provider):
    monkeypatch.setattr(
        "transport.http.security.get_auth_provider", lambda: provider
    )
    return TestClient(create_app(), raise_server_exceptions=False)


class TestMiddlewareStatusMapping:
    def test_unverifiable_credential_yields_503(self, monkeypatch, isolated_server):
        with _client_with_provider(monkeypatch, _RaisingProvider()) as client:
            r = client.get("/api/work", headers={"Authorization": "Bearer t"})

        assert r.status_code == 503
        assert r.headers.get("Retry-After") == "5"
        # Critically: no challenge. A WWW-Authenticate header is what tells a
        # client to throw its token away and make the user sign in again.
        assert "WWW-Authenticate" not in r.headers

    def test_invalid_credential_still_yields_401_with_challenge(
        self, monkeypatch, isolated_server
    ):
        with _client_with_provider(monkeypatch, _RejectingProvider()) as client:
            r = client.get("/api/work", headers={"Authorization": "Bearer t"})

        assert r.status_code == 401
        assert "WWW-Authenticate" in r.headers

    def test_public_paths_unaffected_when_jwks_unreachable(
        self, monkeypatch, isolated_server
    ):
        """Discovery and health must keep working during an Entra outage, or
        a client cannot even re-run the OAuth flow to recover."""
        with _client_with_provider(monkeypatch, _RaisingProvider()) as client:
            assert client.get("/health").status_code == 200
            assert (
                client.get("/.well-known/oauth-protected-resource").status_code == 200
            )


# ===========================================================================
# 4. Readiness gate — do not take traffic until tokens can be verified
# ===========================================================================

class TestReadinessGate:
    def test_ready_is_true_when_entra_not_configured(self):
        """Local / API-key mode has no JWKS to warm."""
        from lib import auth as auth_mod

        with patch.object(auth_mod, "TENANT_ID", ""), patch.object(
            auth_mod, "CLIENT_ID", ""
        ):
            assert auth_mod.jwks_ready() is True

    def test_ready_is_false_under_entra_until_warmed(self):
        from lib import auth as auth_mod

        with patch.object(auth_mod, "TENANT_ID", "t"), patch.object(
            auth_mod, "CLIENT_ID", "c"
        ), patch.object(auth_mod, "_jwks_warm", False):
            assert auth_mod.jwks_ready() is False

    def test_warm_jwks_sets_ready(self):
        from lib import auth as auth_mod

        auth_mod._reset_jwks_state_for_tests()
        try:
            with patch.object(auth_mod, "TENANT_ID", "t"), patch.object(
                auth_mod, "CLIENT_ID", "c"
            ), patch.object(auth_mod, "_get_jwks_client") as get_client:
                assert auth_mod.jwks_ready() is False
                auth_mod.warm_jwks()
                assert auth_mod.jwks_ready() is True
                # Must force a fetch, not trust a possibly-stale cache.
                get_client.return_value.get_signing_keys.assert_called_once_with(
                    refresh=True
                )
        finally:
            auth_mod._reset_jwks_state_for_tests()

    def test_warm_jwks_leaves_pod_unready_on_failure(self):
        from lib import auth as auth_mod

        auth_mod._reset_jwks_state_for_tests()
        try:
            with patch.object(auth_mod, "TENANT_ID", "t"), patch.object(
                auth_mod, "CLIENT_ID", "c"
            ), patch.object(auth_mod, "_get_jwks_client") as get_client:
                get_client.return_value.get_signing_keys.side_effect = (
                    PyJWKClientConnectionError("down")
                )
                with pytest.raises(PyJWKClientConnectionError):
                    auth_mod.warm_jwks()
                assert auth_mod.jwks_ready() is False
        finally:
            auth_mod._reset_jwks_state_for_tests()

    def test_ready_endpoint_200_when_warm(self, monkeypatch, isolated_server):
        reset_settings_cache()
        reset_auth_provider_cache()
        try:
            with patch("lib.auth.jwks_ready", return_value=True):
                with TestClient(create_app()) as client:
                    r = client.get("/ready")
            assert r.status_code == 200
            assert r.json()["jwks"] is True
        finally:
            reset_settings_cache()
            reset_auth_provider_cache()

    def test_ready_endpoint_503_when_cold(self, monkeypatch, isolated_server):
        """A pod that cannot verify signatures must be pulled from the
        ingress rather than answering valid tokens with an auth error."""
        reset_settings_cache()
        reset_auth_provider_cache()
        try:
            with patch("lib.auth.jwks_ready", return_value=False):
                with TestClient(create_app()) as client:
                    r = client.get("/ready")
            assert r.status_code == 503
            assert r.json()["jwks"] is False
        finally:
            reset_settings_cache()
            reset_auth_provider_cache()
