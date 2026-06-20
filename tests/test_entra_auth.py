"""Tests for Entra ID authentication layer.

Covers:
  lib/auth.py
    - validate_token: valid RS256 JWT, expired token, wrong audience, bad signature
    - oauth_discovery_json: field presence + audience scopes
    - EntraAuthMiddleware: no-op (no env vars), public path passthrough,
      missing Bearer → 401, expired → 401, valid → 200 + request.state.user set

  transport/http/security.py
    - EntraAuthProvider.authenticate_request: Bearer token, jc_session cookie,
      invalid token, missing token
    - ApiKeyAuthProvider.authenticate_request: disabled mode, valid key, wrong key
    - get_auth_provider: Entra vars present → EntraAuthProvider,
                         absent → ApiKeyAuthProvider

  transport/http/routes/oauth.py
    - GET  /.well-known/oauth-protected-resource  (plain + /mcp suffix)
    - GET  /.well-known/oauth-authorization-server
    - POST /oauth/register (with + without body, missing ENTRA_CLIENT_ID)
    - GET  /oauth/authorize (strips 'resource', preserves other params)
    - GET  /logout          (redirects to Entra end_session_endpoint)
    - GET  /logged-out      (HTML landing page)
"""

from __future__ import annotations

from pathlib import Path
import time
from typing import Any
from unittest.mock import MagicMock, patch

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from starlette.testclient import TestClient

# ---------------------------------------------------------------------------
# Shared RSA key pair for tests — generated once per session
# ---------------------------------------------------------------------------

_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PUBLIC_KEY = _PRIVATE_KEY.public_key()


def _make_token(
    *,
    audience: str = "test-client-id",
    expired: bool = False,
    extra_claims: dict | None = None,
    private_key=None,
) -> str:
    """Mint a signed RS256 JWT for testing."""
    if private_key is None:
        private_key = _PRIVATE_KEY
    now = int(time.time())
    payload: dict[str, Any] = {
        "aud": audience,
        "iss": "https://login.microsoftonline.com/test-tenant/v2.0",
        "sub": "test-subject",
        "oid": "test-oid-123",
        "name": "Test User",
        "preferred_username": "test@example.com",
        "iat": now - 3600 if expired else now,
        "exp": now - 1 if expired else now + 3600,
    }
    if extra_claims:
        payload.update(extra_claims)
    pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    )
    return jwt.encode(payload, pem, algorithm="RS256")


def _mock_signing_key(token: str):
    """Return a PyJWT-compatible mock signing key backed by _PUBLIC_KEY."""
    mock = MagicMock()
    mock.key = _PUBLIC_KEY
    return mock


# ===========================================================================
# lib/auth.py — validate_token
# ===========================================================================

class TestValidateToken:
    """Unit tests for lib.auth.validate_token.

    We patch _get_jwks_client so no network call is made, and we control the
    CLIENT_ID env var so audience checks are deterministic.
    """

    def _run(self, token: str, client_id: str = "test-client-id"):
        from lib import auth as auth_mod
        mock_client = MagicMock()
        mock_client.get_signing_key_from_jwt.return_value = _mock_signing_key(token)

        with (
            patch.object(auth_mod, "_get_jwks_client", return_value=mock_client),
            patch.object(auth_mod, "CLIENT_ID", client_id),
        ):
            return auth_mod.validate_token(token)

    def test_valid_token_returns_claims(self):
        token = _make_token(audience="test-client-id")
        claims = self._run(token)
        assert claims["oid"] == "test-oid-123"
        assert claims["name"] == "Test User"

    def test_api_audience_prefix_accepted(self):
        """api://<CLIENT_ID> audience variant (Entra v1 tokens)."""
        token = _make_token(audience="api://test-client-id")
        claims = self._run(token)
        assert claims["sub"] == "test-subject"

    def test_expired_token_raises(self):
        token = _make_token(expired=True)
        with pytest.raises(jwt.ExpiredSignatureError):
            self._run(token)

    def test_wrong_audience_raises(self):
        token = _make_token(audience="wrong-client-id")
        with pytest.raises(jwt.InvalidTokenError):
            self._run(token)

    def test_bad_signature_raises(self):
        # Sign with a different key — JWKS returns the wrong public key
        other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        token = _make_token(private_key=other_key)
        # Our mock returns _PUBLIC_KEY for this token → signature mismatch
        with pytest.raises(jwt.InvalidTokenError):
            self._run(token)


# ===========================================================================
# lib/auth.py — oauth_discovery_json
# ===========================================================================

class TestOauthDiscoveryJson:
    def test_required_fields_present(self):
        from lib import auth as auth_mod
        with patch.object(auth_mod, "TENANT_ID", "my-tenant"):
            data = auth_mod.oauth_discovery_json()
        assert "authorization_endpoint" in data
        assert "token_endpoint" in data
        assert "jwks_uri" in data
        assert "code_challenge_methods_supported" in data
        assert "S256" in data["code_challenge_methods_supported"]

    def test_scopes_include_api_prefix(self):
        from lib import auth as auth_mod
        with (
            patch.object(auth_mod, "TENANT_ID", "my-tenant"),
            patch.object(auth_mod, "CLIENT_ID", "abc123"),
        ):
            data = auth_mod.oauth_discovery_json()
        assert any("api://" in s for s in data["scopes_supported"])

    def test_grant_types(self):
        from lib import auth as auth_mod
        with patch.object(auth_mod, "TENANT_ID", "my-tenant"):
            data = auth_mod.oauth_discovery_json()
        assert "authorization_code" in data["grant_types_supported"]


# ===========================================================================
# lib/auth.py — EntraAuthMiddleware
# ===========================================================================

class TestEntraAuthMiddleware:
    """Integration-style tests using a minimal Starlette app."""

    def _make_app(self, tenant_id: str = "t1", client_id: str = "c1"):
        from fastapi import FastAPI, Request
        from lib.auth import EntraAuthMiddleware

        inner = FastAPI()

        @inner.get("/protected")
        async def protected(request: Request):
            from starlette.responses import JSONResponse
            user = getattr(request.state, "user", None)
            return JSONResponse({"user": user})

        @inner.get("/health")
        async def health():
            from starlette.responses import JSONResponse
            return JSONResponse({"ok": True})

        inner.add_middleware(EntraAuthMiddleware)
        return inner

    def test_noop_when_env_vars_missing(self, monkeypatch, isolated_server):
        """Middleware is a no-op in local mode (no ENTRA vars) — any health call returns 200."""
        from fastapi.testclient import TestClient
        from transport.http.app import create_app
        from transport.http.config import reset_settings_cache
        from transport.http.security import reset_auth_provider_cache

        monkeypatch.delenv("ENTRA_TENANT_ID", raising=False)
        monkeypatch.delenv("ENTRA_CLIENT_ID", raising=False)
        monkeypatch.delenv("API_KEY", raising=False)
        reset_settings_cache()
        reset_auth_provider_cache()
        app = create_app()
        with TestClient(app) as client:
            r = client.get("/health")
        assert r.status_code == 200
        reset_settings_cache()
        reset_auth_provider_cache()

    def test_public_path_passthrough(self):
        """Health endpoint passes even with auth enabled."""
        from lib import auth as auth_mod
        with (
            patch.object(auth_mod, "TENANT_ID", "tenant"),
            patch.object(auth_mod, "CLIENT_ID", "client"),
        ):
            app = self._make_app()
            client = TestClient(app, raise_server_exceptions=True)
            r = client.get("/health")
        assert r.status_code == 200

    def test_missing_bearer_returns_401(self):
        from lib import auth as auth_mod
        with (
            patch.object(auth_mod, "TENANT_ID", "tenant"),
            patch.object(auth_mod, "CLIENT_ID", "client"),
        ):
            app = self._make_app()
            client = TestClient(app, raise_server_exceptions=True)
            r = client.get("/protected")
        assert r.status_code == 401
        assert "WWW-Authenticate" in r.headers

    def test_expired_token_returns_401(self):
        token = _make_token(expired=True)
        from lib import auth as auth_mod
        mock_client = MagicMock()
        mock_client.get_signing_key_from_jwt.return_value = _mock_signing_key(token)

        with (
            patch.object(auth_mod, "TENANT_ID", "tenant"),
            patch.object(auth_mod, "CLIENT_ID", "client"),
            patch.object(auth_mod, "_get_jwks_client", return_value=mock_client),
        ):
            app = self._make_app()
            client = TestClient(app, raise_server_exceptions=False)
            r = client.get("/protected", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 401
        assert "expired" in r.json().get("message", "").lower()

    def test_valid_token_sets_user_state(self, monkeypatch, isolated_server):
        """Valid bearer token passes through middleware and request.state.user is populated.

        Tested via EntraAuthProvider (which calls validate_token) since the
        UserDataContextMiddleware calls the provider directly.
        """
        from transport.http.security import EntraAuthProvider, reset_auth_provider_cache
        monkeypatch.setenv("ENTRA_TENANT_ID", "tenant")
        monkeypatch.setenv("ENTRA_CLIENT_ID", "client")
        reset_auth_provider_cache()

        token = _make_token(audience="client")
        with patch("lib.auth.validate_token", return_value={"oid": "u1", "name": "Eve"}):
            provider = EntraAuthProvider()
            user = provider.authenticate_request(f"Bearer {token}", None)

        assert user is not None
        assert user.id == "u1"
        assert user.name == "Eve"
        reset_auth_provider_cache()


# ===========================================================================
# transport/http/security.py — EntraAuthProvider
# ===========================================================================

class TestEntraAuthProvider:
    def _provider(self):
        from transport.http.security import EntraAuthProvider
        return EntraAuthProvider()

    def _mock_validate(self, token: str, claims: dict | None = None, raises=None):
        from lib import auth as auth_mod
        if raises:
            return patch("lib.auth.validate_token", side_effect=raises)
        return patch("lib.auth.validate_token", return_value=claims or {
            "oid": "oid-abc",
            "name": "Alice",
        })

    def test_valid_bearer_returns_user(self):
        provider = self._provider()
        token = _make_token()
        with self._mock_validate(token):
            user = provider.authenticate_request(f"Bearer {token}", None)
        assert user is not None
        assert user.id == "oid-abc"
        assert user.name == "Alice"

    def test_valid_session_cookie_returns_user(self):
        provider = self._provider()
        token = _make_token()
        with self._mock_validate(token):
            user = provider.authenticate_request(None, token)
        assert user is not None
        assert user.id == "oid-abc"

    def test_bearer_takes_precedence_over_cookie(self):
        provider = self._provider()
        token = _make_token()
        with self._mock_validate(token):
            user = provider.authenticate_request(f"Bearer {token}", "other-token")
        assert user is not None

    def test_missing_token_returns_none(self):
        provider = self._provider()
        user = provider.authenticate_request(None, None)
        assert user is None

    def test_invalid_token_returns_none(self):
        provider = self._provider()
        with patch("lib.auth.validate_token", side_effect=jwt.InvalidTokenError("bad")):
            user = provider.authenticate_request("Bearer garbage", None)
        assert user is None

    def test_auth_enabled_always_true(self):
        assert self._provider().auth_enabled is True

    def test_authenticate_login_returns_none(self):
        """Browser PKCE flow — login form is not used."""
        assert self._provider().authenticate_login("anything") is None

    def test_oid_falls_back_to_sub(self):
        """When oid claim is absent, sub is used as user id."""
        provider = self._provider()
        token = _make_token()
        with patch("lib.auth.validate_token", return_value={"sub": "sub-xyz", "name": "Bob"}):
            user = provider.authenticate_request(f"Bearer {token}", None)
        assert user is not None
        assert user.id == "sub-xyz"


# ===========================================================================
# transport/http/security.py — ApiKeyAuthProvider
# ===========================================================================

class TestApiKeyAuthProvider:
    def _provider(self):
        from transport.http.security import ApiKeyAuthProvider
        return ApiKeyAuthProvider()

    def test_no_key_configured_returns_system_user(self, monkeypatch):
        monkeypatch.delenv("API_KEY", raising=False)
        from transport.http.config import reset_settings_cache
        reset_settings_cache()
        provider = self._provider()
        user = provider.authenticate_request(None, None)
        assert user is not None
        assert user.id == "admin"
        reset_settings_cache()

    def test_correct_key_via_bearer_returns_user(self, monkeypatch):
        monkeypatch.setenv("API_KEY", "my-key")
        from transport.http.config import reset_settings_cache
        reset_settings_cache()
        provider = self._provider()
        user = provider.authenticate_request("Bearer my-key", None)
        assert user is not None
        reset_settings_cache()

    def test_correct_key_via_cookie_returns_user(self, monkeypatch):
        monkeypatch.setenv("API_KEY", "my-key")
        from transport.http.config import reset_settings_cache
        reset_settings_cache()
        provider = self._provider()
        user = provider.authenticate_request(None, "my-key")
        assert user is not None
        reset_settings_cache()

    def test_wrong_key_returns_none(self, monkeypatch):
        monkeypatch.setenv("API_KEY", "my-key")
        from transport.http.config import reset_settings_cache
        reset_settings_cache()
        provider = self._provider()
        user = provider.authenticate_request("Bearer wrong", None)
        assert user is None
        reset_settings_cache()


# ===========================================================================
# transport/http/security.py — get_auth_provider factory
# ===========================================================================

class TestGetAuthProvider:
    def test_returns_entra_provider_when_env_vars_set(self, monkeypatch):
        monkeypatch.setenv("ENTRA_TENANT_ID", "tenant")
        monkeypatch.setenv("ENTRA_CLIENT_ID", "client")
        from transport.http.security import get_auth_provider, reset_auth_provider_cache, EntraAuthProvider
        reset_auth_provider_cache()
        provider = get_auth_provider()
        assert isinstance(provider, EntraAuthProvider)
        reset_auth_provider_cache()

    def test_returns_apikey_provider_when_env_vars_absent(self, monkeypatch):
        monkeypatch.delenv("ENTRA_TENANT_ID", raising=False)
        monkeypatch.delenv("ENTRA_CLIENT_ID", raising=False)
        from transport.http.security import get_auth_provider, reset_auth_provider_cache, ApiKeyAuthProvider
        reset_auth_provider_cache()
        provider = get_auth_provider()
        assert isinstance(provider, ApiKeyAuthProvider)
        reset_auth_provider_cache()

    def test_partial_env_vars_fall_back_to_apikey(self, monkeypatch):
        monkeypatch.setenv("ENTRA_TENANT_ID", "tenant")
        monkeypatch.delenv("ENTRA_CLIENT_ID", raising=False)
        from transport.http.security import get_auth_provider, reset_auth_provider_cache, ApiKeyAuthProvider
        reset_auth_provider_cache()
        provider = get_auth_provider()
        assert isinstance(provider, ApiKeyAuthProvider)
        reset_auth_provider_cache()


# ===========================================================================
# transport/http/routes/oauth.py — discovery + registration + proxies
# ===========================================================================

@pytest.fixture()
def oauth_client(monkeypatch, isolated_server):
    """TestClient with Entra env vars set and oauth router mounted."""
    monkeypatch.setenv("ENTRA_TENANT_ID", "test-tenant")
    monkeypatch.setenv("ENTRA_CLIENT_ID", "test-client-id")
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.delenv("ENTRA_OWNER_OID", raising=False)
    from transport.http.config import reset_settings_cache
    from transport.http.security import reset_auth_provider_cache
    reset_settings_cache()
    reset_auth_provider_cache()
    from transport.http.app import create_app
    app = create_app()
    with TestClient(app, raise_server_exceptions=True) as client:
        yield client
    reset_settings_cache()
    reset_auth_provider_cache()


class TestOauthProtectedResource:
    def test_returns_resource_and_auth_servers(self, oauth_client):
        r = oauth_client.get("/.well-known/oauth-protected-resource")
        assert r.status_code == 200
        data = r.json()
        assert "resource" in data
        assert "authorization_servers" in data
        assert len(data["authorization_servers"]) >= 1

    def test_mcp_path_suffix_also_responds(self, oauth_client):
        r = oauth_client.get("/.well-known/oauth-protected-resource/mcp")
        assert r.status_code == 200
        assert "resource" in r.json()

    def test_bearer_methods_supported(self, oauth_client):
        r = oauth_client.get("/.well-known/oauth-protected-resource")
        assert "header" in r.json().get("bearer_methods_supported", [])


class TestOauthAuthorizationServer:
    def test_returns_required_fields(self, oauth_client):
        r = oauth_client.get("/.well-known/oauth-authorization-server")
        assert r.status_code == 200
        data = r.json()
        for key in ("authorization_endpoint", "token_endpoint", "jwks_uri",
                    "registration_endpoint", "scopes_supported"):
            assert key in data, f"missing {key}"

    def test_registration_endpoint_points_to_our_server(self, oauth_client):
        r = oauth_client.get("/.well-known/oauth-authorization-server")
        reg = r.json()["registration_endpoint"]
        assert "/oauth/register" in reg

    def test_auth_endpoint_points_to_our_proxy(self, oauth_client):
        """Must be our /oauth/authorize proxy, not Entra directly."""
        r = oauth_client.get("/.well-known/oauth-authorization-server")
        auth_ep = r.json()["authorization_endpoint"]
        assert "login.microsoftonline.com" not in auth_ep
        assert "/oauth/authorize" in auth_ep


class TestOauthDynamicRegister:
    def test_returns_client_id(self, oauth_client):
        r = oauth_client.post("/oauth/register", json={
            "redirect_uris": ["http://localhost/callback"],
        })
        assert r.status_code == 201
        data = r.json()
        assert data["client_id"] == "test-client-id"

    def test_echoes_redirect_uris(self, oauth_client):
        uris = ["http://localhost/callback", "https://claude.ai/oauth/callback"]
        r = oauth_client.post("/oauth/register", json={"redirect_uris": uris})
        assert r.json()["redirect_uris"] == uris

    def test_public_client_no_secret(self, oauth_client):
        r = oauth_client.post("/oauth/register", json={})
        assert r.json()["token_endpoint_auth_method"] == "none"

    def test_empty_body_still_works(self, oauth_client):
        r = oauth_client.post("/oauth/register")
        assert r.status_code == 201

    def test_503_when_no_client_id(self, monkeypatch, isolated_server):
        monkeypatch.setenv("ENTRA_TENANT_ID", "t")
        monkeypatch.delenv("ENTRA_CLIENT_ID", raising=False)
        from transport.http.config import reset_settings_cache
        from transport.http.security import reset_auth_provider_cache
        reset_settings_cache()
        reset_auth_provider_cache()
        from transport.http.app import create_app
        app = create_app()
        client = TestClient(app, raise_server_exceptions=True)
        r = client.post("/oauth/register", json={})
        assert r.status_code == 503
        reset_settings_cache()
        reset_auth_provider_cache()


class TestOauthAuthorizeProxy:
    def test_redirects_to_entra(self, oauth_client):
        r = oauth_client.get(
            "/oauth/authorize",
            params={
                "response_type": "code",
                "client_id": "test-client-id",
                "redirect_uri": "http://localhost/callback",
                "code_challenge": "abc123",
                "code_challenge_method": "S256",
                "resource": "https://jobcontextmcp.example.com",  # must be stripped
            },
            follow_redirects=False,
        )
        assert r.status_code == 302
        location = r.headers["location"]
        assert "login.microsoftonline.com" in location

    def test_resource_param_stripped(self, oauth_client):
        r = oauth_client.get(
            "/oauth/authorize",
            params={"resource": "https://evil.com", "client_id": "cid"},
            follow_redirects=False,
        )
        assert r.status_code == 302
        location = r.headers["location"]
        assert "resource=" not in location

    def test_pkce_params_preserved(self, oauth_client):
        r = oauth_client.get(
            "/oauth/authorize",
            params={
                "code_challenge": "mychallenge",
                "code_challenge_method": "S256",
                "state": "mystate",
            },
            follow_redirects=False,
        )
        assert r.status_code == 302
        location = r.headers["location"]
        assert "code_challenge=mychallenge" in location
        assert "state=mystate" in location


class TestLogoutEndpoints:
    def test_logout_redirects_to_entra(self, oauth_client):
        r = oauth_client.get("/logout", follow_redirects=False)
        assert r.status_code == 302
        assert "login.microsoftonline.com" in r.headers["location"]
        assert "logout" in r.headers["location"]

    def test_logout_includes_post_logout_redirect(self, oauth_client):
        r = oauth_client.get("/logout", follow_redirects=False)
        assert "post_logout_redirect_uri" in r.headers["location"]

    def test_logged_out_page_returns_html(self, oauth_client):
        r = oauth_client.get("/logged-out")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]
        assert "Signed out" in r.text

    def test_logged_out_page_has_cache_clear_instructions(self, oauth_client):
        r = oauth_client.get("/logged-out")
        assert "mcp-remote" in r.text or "rm -rf" in r.text


class _StubAuthProvider:
    def __init__(self, user):
        self._user = user

    @property
    def auth_enabled(self) -> bool:
        return True

    def authenticate_request(self, authorization: str | None, session_token: str | None):
        return self._user

    def authenticate_login(self, credential: str):
        return None


class TestUserDataContextMiddleware:
    def test_routes_authenticated_user_to_user_partition(self, monkeypatch, isolated_server):
        from lib import config
        from transport.http.app import create_app
        from transport.http.security import User

        user_ws = Path(config.DATA_FOLDER) / "users" / "u1" / "workspace"
        (user_ws / "02-Cover-Letters").mkdir(parents=True, exist_ok=True)
        (user_ws / "02-Cover-Letters" / "u1-cover-letter.txt").write_text("hello", encoding="utf-8")

        provider = _StubAuthProvider(User(id="u1", name="Normal User", roles=("user",)))
        monkeypatch.setattr("transport.http.security.get_auth_provider", lambda: provider)
        monkeypatch.setattr("transport.http.auth.get_auth_provider", lambda: provider)

        app = create_app()
        with TestClient(app, raise_server_exceptions=True) as client:
            r = client.get("/dashboard/materials/data")

        assert r.status_code == 200
        data = r.json()
        assert data["cover_letters"] >= 1
        names = [f["name"] for f in data["folders"]["cover_letters"]["files"]]
        assert "u1-cover-letter.txt" in names

    def test_admin_api_key_session_cannot_access_tenant_data(self, monkeypatch, isolated_server):
        from transport.http.app import create_app
        from transport.http.security import User

        provider = _StubAuthProvider(User(id="admin", name="System", roles=("admin",)))
        monkeypatch.setattr("transport.http.security.get_auth_provider", lambda: provider)
        monkeypatch.setattr("transport.http.auth.get_auth_provider", lambda: provider)

        app = create_app()
        with TestClient(app, raise_server_exceptions=True) as client:
            r = client.get("/dashboard/materials/data")

        assert r.status_code == 403
        assert "not tenant-scoped" in r.json().get("message", "")
