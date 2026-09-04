"""ChatGPT key bridge: OAuth code flow fronting the per-user API-key system.

ChatGPT's MCP connector only speaks OAuth (authorization-code + PKCE) — it
cannot present a static API key. The bridge in transport/http/routes/oauth.py
serves a consent page (jc_session-authenticated) for allowlisted ChatGPT
callback URIs, mints a one-time code, and exchanges it for a freshly created
jcmcp_ key, which /mcp already accepts.

Covers:
- unauthenticated consent GET bounces through /dashboard/login with next intact
- non-bridge redirect_uris still proxy to Entra byte-identically
- PKCE (S256) required at authorize; verified at token exchange
- approve: mints code, re-validates redirect_uri, rejects cross-site posts
  and unauthenticated posts
- token: code is single-use, expiring, bound to redirect_uri and oid;
  the returned access_token resolves to the approving user's oid
"""
from __future__ import annotations

import base64
import hashlib
import sqlite3
from urllib.parse import parse_qs, quote, urlparse

import pytest

# ChatGPT's callback is per-connector: an opaque id under /connector/oauth/.
_CHATGPT_REDIRECT = "https://chatgpt.com/connector/oauth/h4dVACDiDUTH"
_VERIFIER = "test-verifier-" + "x" * 43


def _challenge(verifier: str = _VERIFIER) -> str:
    return (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )


def _authorize_query(redirect_uri: str = _CHATGPT_REDIRECT, **overrides) -> dict:
    params = {
        "client_id": "fake-client",
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "state": "st-123",
        "code_challenge": _challenge(),
        "code_challenge_method": "S256",
    }
    params.update(overrides)
    return {k: v for k, v in params.items() if v is not None}


@pytest.fixture()
def bridge_client(monkeypatch, isolated_server, tmp_path):
    """TestClient in Entra mode with a schema'd global DB for API keys."""
    from scripts.migrate_to_sqlite import _SCHEMA
    import lib.db as _db

    db_file = tmp_path / "keybridge-global.db"
    con = sqlite3.connect(db_file)
    con.executescript(_SCHEMA)
    con.commit()
    con.close()
    monkeypatch.setattr(_db, "global_db_path", lambda: db_file)
    monkeypatch.setattr(_db, "db_path", lambda: db_file)

    monkeypatch.setenv("ENTRA_TENANT_ID", "fake-tenant")
    monkeypatch.setenv("ENTRA_CLIENT_ID", "fake-client")
    monkeypatch.delenv("API_KEY", raising=False)

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


@pytest.fixture()
def alice_cookie(bridge_client):
    """Sign 'oid-alice' in: a jcmcp_ key doubles as a valid jc_session value
    (EntraAuthProvider resolves the prefix before JWT validation)."""
    from lib.api_keys import create_key

    _, plaintext = create_key("oid-alice", "session-stand-in")
    bridge_client.cookies.clear()
    bridge_client.cookies.set("jc_session", plaintext)
    return plaintext


def _approve(client, state="st-123", challenge=None, redirect_uri=_CHATGPT_REDIRECT):
    return client.post(
        "/oauth/authorize/approve",
        data={
            "redirect_uri": redirect_uri,
            "state": state,
            "code_challenge": challenge or _challenge(),
        },
        follow_redirects=False,
    )


def _code_from(response) -> str:
    location = response.headers["location"]
    assert location.startswith(_CHATGPT_REDIRECT)
    return parse_qs(urlparse(location).query)["code"][0]


def _exchange(client, code, verifier=_VERIFIER, redirect_uri=_CHATGPT_REDIRECT):
    return client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "code_verifier": verifier,
            "client_id": "fake-client",
        },
    )


class TestAuthorize:
    def test_unauthenticated_bounces_to_login_with_next(self, bridge_client):
        r = bridge_client.get(
            "/oauth/authorize", params=_authorize_query(), follow_redirects=False
        )
        assert r.status_code == 303
        assert r.headers["location"].startswith("/dashboard/login?next=")
        assert quote("/oauth/authorize", safe="") in r.headers["location"]

    def test_non_bridge_redirect_uri_still_proxies_to_entra(self, bridge_client):
        r = bridge_client.get(
            "/oauth/authorize",
            params=_authorize_query(redirect_uri="https://claude.ai/oauth/callback"),
            follow_redirects=False,
        )
        assert r.status_code == 302
        assert r.headers["location"].startswith(
            "https://login.microsoftonline.com/fake-tenant/oauth2/v2.0/authorize"
        )

    def test_missing_code_challenge_rejected(self, bridge_client, alice_cookie):
        r = bridge_client.get(
            "/oauth/authorize",
            params=_authorize_query(code_challenge=None),
            follow_redirects=False,
        )
        assert r.status_code == 400
        assert r.json()["error"] == "invalid_request"

    def test_plain_pkce_method_rejected(self, bridge_client, alice_cookie):
        r = bridge_client.get(
            "/oauth/authorize",
            params=_authorize_query(code_challenge_method="plain"),
            follow_redirects=False,
        )
        assert r.status_code == 400

    def test_authenticated_user_sees_consent_page(self, bridge_client, alice_cookie):
        r = bridge_client.get(
            "/oauth/authorize", params=_authorize_query(), follow_redirects=False
        )
        assert r.status_code == 200
        assert "Approve" in r.text
        assert _challenge() in r.text  # hidden field carries the challenge


class TestApprove:
    def test_mints_code_and_redirects_to_chatgpt(self, bridge_client, alice_cookie):
        r = _approve(bridge_client)
        assert r.status_code == 303
        location = r.headers["location"]
        assert location.startswith(_CHATGPT_REDIRECT)
        qs = parse_qs(urlparse(location).query)
        assert qs["code"][0].startswith("jcac_")
        assert qs["state"] == ["st-123"]

    def test_cross_site_post_rejected(self, bridge_client, alice_cookie):
        r = bridge_client.post(
            "/oauth/authorize/approve",
            data={
                "redirect_uri": _CHATGPT_REDIRECT,
                "state": "s",
                "code_challenge": _challenge(),
            },
            headers={"Sec-Fetch-Site": "cross-site"},
            follow_redirects=False,
        )
        assert r.status_code == 403

    def test_unauthenticated_post_rejected(self, bridge_client):
        bridge_client.cookies.clear()
        r = _approve(bridge_client)
        assert r.status_code == 401

    def test_unlisted_redirect_uri_rejected(self, bridge_client, alice_cookie):
        r = _approve(bridge_client, redirect_uri="https://evil.example/callback")
        assert r.status_code == 400


class TestTokenExchange:
    def test_full_flow_returns_key_scoped_to_approving_user(
        self, bridge_client, alice_cookie
    ):
        from lib.api_keys import lookup_key

        code = _code_from(_approve(bridge_client))
        r = _exchange(bridge_client, code)
        assert r.status_code == 200
        body = r.json()
        assert body["token_type"] == "bearer"
        token = body["access_token"]
        assert token.startswith("jcmcp_")
        # The credential resolves to the user who approved — never anyone else.
        assert lookup_key(token) == "oid-alice"
        assert r.headers["cache-control"] == "no-store"

    def test_issued_key_is_labeled_and_revocable(self, bridge_client, alice_cookie):
        from lib.api_keys import list_keys

        code = _code_from(_approve(bridge_client))
        assert _exchange(bridge_client, code).status_code == 200
        labels = [k.label for k in list_keys("oid-alice")]
        assert "ChatGPT connector" in labels

    def test_wrong_verifier_rejected_and_code_burned(self, bridge_client, alice_cookie):
        code = _code_from(_approve(bridge_client))
        r = _exchange(bridge_client, code, verifier="wrong-verifier-" + "y" * 43)
        assert r.status_code == 400
        assert r.json()["error"] == "invalid_grant"
        # Single-use even on failure: the correct verifier can't save it now.
        assert _exchange(bridge_client, code).status_code == 400

    def test_code_is_single_use(self, bridge_client, alice_cookie):
        code = _code_from(_approve(bridge_client))
        assert _exchange(bridge_client, code).status_code == 200
        assert _exchange(bridge_client, code).status_code == 400

    def test_redirect_uri_must_match(self, bridge_client, alice_cookie):
        code = _code_from(_approve(bridge_client))
        r = _exchange(
            bridge_client, code,
            redirect_uri="https://chatgpt.com/connector/oauth/DIFFERENTconn",
        )
        assert r.status_code == 400

    def test_expired_code_rejected(self, bridge_client, alice_cookie):
        from transport.http.routes import oauth as oauth_module

        code = _code_from(_approve(bridge_client))
        oauth_module._bridge_codes[code]["expires"] -= 10_000
        assert _exchange(bridge_client, code).status_code == 400

    def test_unknown_code_rejected(self, bridge_client, alice_cookie):
        assert _exchange(bridge_client, "jcac_neverissued123").status_code == 400

    def test_non_code_grant_with_bridge_code_rejected(self, bridge_client, alice_cookie):
        code = _code_from(_approve(bridge_client))
        r = bridge_client.post(
            "/oauth/token",
            data={"grant_type": "client_credentials", "code": code},
        )
        assert r.status_code == 400
        assert r.json()["error"] == "unsupported_grant_type"


class TestBridgeGating:
    def test_disabled_outside_entra_mode(self, monkeypatch):
        from transport.http.routes.oauth import _bridge_enabled

        monkeypatch.delenv("ENTRA_CLIENT_ID", raising=False)
        assert _bridge_enabled() is False

    def test_redirect_allowlist_env_override(self, monkeypatch):
        from transport.http.routes.oauth import _is_bridge_redirect_uri

        monkeypatch.setenv(
            "KEYBRIDGE_REDIRECT_URIS",
            "https://a.example/cb, https://b.example/oauth/*",
        )
        assert _is_bridge_redirect_uri("https://a.example/cb") is True
        assert _is_bridge_redirect_uri("https://a.example/cb2") is False  # exact
        assert _is_bridge_redirect_uri("https://b.example/oauth/anything") is True
        # Override REPLACES the defaults — ChatGPT's callback is out until listed.
        assert _is_bridge_redirect_uri(_CHATGPT_REDIRECT) is False


class TestRedirectMatching:
    def test_any_connector_id_matches_default_prefix(self):
        from transport.http.routes.oauth import _is_bridge_redirect_uri

        assert _is_bridge_redirect_uri("https://chatgpt.com/connector/oauth/AbC123xyz")
        assert _is_bridge_redirect_uri("https://chat.openai.com/connector/oauth/Zz9")

    def test_other_hosts_and_roots_rejected(self):
        from transport.http.routes.oauth import _is_bridge_redirect_uri

        assert not _is_bridge_redirect_uri("https://evil.example/connector/oauth/x")
        assert not _is_bridge_redirect_uri("https://chatgpt.com.evil.example/connector/oauth/x")
        assert not _is_bridge_redirect_uri("https://chatgpt.com/other/path")
        assert not _is_bridge_redirect_uri("http://chatgpt.com/connector/oauth/x")  # scheme pinned

    def test_hygiene_rules_on_prefix_matches(self):
        from transport.http.routes.oauth import _is_bridge_redirect_uri

        assert not _is_bridge_redirect_uri("https://chatgpt.com/connector/oauth/x?code=fake")
        assert not _is_bridge_redirect_uri("https://chatgpt.com/connector/oauth/x#frag")
        assert not _is_bridge_redirect_uri("https://chatgpt.com/connector/oauth/../../evil")
        assert not _is_bridge_redirect_uri("https://chatgpt.com/connector/oauth/x\\y")
        assert not _is_bridge_redirect_uri("")
