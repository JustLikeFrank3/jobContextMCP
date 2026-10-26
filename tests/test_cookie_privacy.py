"""Browser-storage inventory exercised with synthetic, in-process auth only.

No Microsoft/Oura credentials, outbound requests, or browser profiles are used.
These tests cover app-owned cookies; identity-provider cookies are out of scope.
"""
from __future__ import annotations

import base64
import hashlib
from http.cookies import SimpleCookie
import re
import socket
from urllib.parse import parse_qs, urlsplit

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from jwt import InvalidTokenError
import pytest

from transport.http.auth import require_authenticated_user
from transport.http.config import reset_settings_cache
from transport.http.routes import oauth
from transport.http.routes.dashboard import login, oura
from transport.http.security import User, reset_auth_provider_cache


def cookies(response):
    """Preserve separate Set-Cookie headers, including deletion directives."""
    parsed = SimpleCookie()
    for header in response.headers.get_list("set-cookie"):
        parsed.load(header)
    return parsed


def assert_security_cookie(cookie, *, seconds, same_site="lax"):
    assert cookie["max-age"] == str(seconds)
    assert cookie["path"] == "/"
    assert cookie["httponly"] is True
    assert cookie["secure"] is True
    assert cookie["samesite"] == same_site
    assert not cookie["domain"]


@pytest.fixture()
def synthetic_browser(monkeypatch, isolated_server):
    """Real auth routes/providers, synthetic token exchange, no lifespan jobs."""
    for name in ("API_KEY", "ENTRA_OWNER_OID", "ENABLE_REMOTE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ENTRA_TENANT_ID", "synthetic-tenant")
    monkeypatch.setenv("ENTRA_CLIENT_ID", "synthetic-client")
    monkeypatch.setenv("ENTRA_CLIENT_SECRET", "synthetic-not-a-secret")
    monkeypatch.setenv("SERVER_BASE_URL", "https://testserver")
    monkeypatch.setattr(login, "_SERVER_BASE", "https://testserver")
    monkeypatch.setattr(oura, "_SERVER_BASE", "https://testserver")
    reset_settings_cache()
    reset_auth_provider_cache()

    def no_network(*_args, **_kwargs):
        pytest.fail("Cookie inventory must not open an outbound connection")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(socket.socket, "connect_ex", no_network)
    exchange = {"calls": [], "status": 200}

    class SyntheticTokenClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def post(self, url, data):
            exchange["calls"].append((url, data))

            class Response:
                status_code = exchange["status"]
                text = "Synthetic token response"

                def json(self):
                    return {"access_token": "synthetic-access-token"}

            return Response()

    monkeypatch.setattr(login.httpx, "AsyncClient", SyntheticTokenClient)

    def validate_synthetic_token(token):
        if token != "synthetic-access-token":
            raise InvalidTokenError("Not the synthetic session")
        return {"oid": "synthetic-user", "name": "Synthetic User"}

    monkeypatch.setattr("lib.auth.validate_token", validate_synthetic_token)
    app = FastAPI()
    app.include_router(login.router, prefix="/dashboard")
    app.include_router(oura.router, prefix="/dashboard")
    app.include_router(oauth.router)

    @app.get("/private")
    def private(user: User = Depends(require_authenticated_user)):
        return {"user": user.id}

    with TestClient(app, base_url="https://testserver") as client:
        yield client, exchange
    reset_settings_cache()
    reset_auth_provider_cache()


def test_entra_handshake_session_and_logout_match_disclosed_inventory(synthetic_browser):
    client, exchange = synthetic_browser
    assert client.get("/private").status_code == 401
    start = client.get("/dashboard/login?next=/app", follow_redirects=False)
    assert set(cookies(start)) == {"pkce_verifier"}
    verifier = cookies(start)["pkce_verifier"]
    assert_security_cookie(verifier, seconds=600)
    target = urlsplit(start.headers["location"])
    assert target.netloc == "login.microsoftonline.com"
    params = parse_qs(target.query)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.value.encode()).digest()).rstrip(b"=").decode()
    assert params["code_challenge"] == [challenge]
    assert params["code_challenge_method"] == ["S256"]
    assert exchange["calls"] == []  # redirect only; no silent analytics request

    callback = client.get("/dashboard/callback?code=synthetic-code&state=/app", follow_redirects=False)
    assert callback.status_code == 303
    assert callback.headers["location"] == "/app"
    assert set(cookies(callback)) == {"jc_session", "pkce_verifier"}
    assert_security_cookie(cookies(callback)["jc_session"], seconds=3600)
    assert cookies(callback)["pkce_verifier"]["max-age"] == "0"
    assert set(client.cookies.keys()) == {"jc_session"}
    assert exchange["calls"][0][0] == "https://login.microsoftonline.com/synthetic-tenant/oauth2/v2.0/token"
    assert exchange["calls"][0][1]["code_verifier"] == verifier.value
    assert client.get("/private").json() == {"user": "synthetic-user"}

    logout = client.post("/logout", follow_redirects=False)
    assert logout.status_code == 303
    assert set(cookies(logout)) == {"jc_session"}
    assert_security_cookie(cookies(logout)["jc_session"], seconds=0)
    assert urlsplit(logout.headers["location"]).netloc == "login.microsoftonline.com"
    assert not client.cookies
    assert client.get("/private").status_code == 401


@pytest.mark.parametrize("method,path", [("post", "/dashboard/logout"), ("post", "/logout"), ("get", "/logout")])
@pytest.mark.parametrize("mode", ["entra", "api-key"])
@pytest.mark.parametrize("has_session", [True, False])
def test_all_signout_routes_remove_session_without_changing_redirects(
    synthetic_browser, monkeypatch, method, path, mode, has_session,
):
    client, _ = synthetic_browser
    session = "synthetic-access-token"
    if mode == "api-key":
        monkeypatch.delenv("ENTRA_TENANT_ID")
        monkeypatch.delenv("ENTRA_CLIENT_ID")
        monkeypatch.setenv("API_KEY", "synthetic-local-key")
        reset_settings_cache()
        reset_auth_provider_cache()
        session = "synthetic-local-key"
    if has_session:
        client.cookies.set("jc_session", session, domain="testserver.local", path="/")
    assert client.get("/private").status_code == (200 if has_session else 401)
    response = getattr(client, method)(path, follow_redirects=False)
    assert response.status_code == (302 if method == "get" else 303)
    if mode == "entra" or method == "get":
        assert urlsplit(response.headers["location"]).netloc == "login.microsoftonline.com"
    else:
        assert response.headers["location"] == ("/dashboard/login" if path.startswith("/dashboard") else "/")
    assert set(cookies(response)) == {"jc_session"}
    assert_security_cookie(cookies(response)["jc_session"], seconds=0)
    assert not client.cookies
    assert client.get("/private").status_code == 401


@pytest.mark.parametrize("callback,expected", [
    ("/dashboard/callback?error=access_denied", 400),
    ("/dashboard/callback?code=synthetic-code", 302),
])
def test_interrupted_login_never_creates_a_session(synthetic_browser, callback, expected):
    client, exchange = synthetic_browser
    response = client.get(callback, follow_redirects=False)
    assert response.status_code == expected
    assert not cookies(response)
    assert not client.cookies
    assert exchange["calls"] == []


def test_repeated_login_rotates_only_handshake_cookie_and_rejected_exchange_keeps_no_session(synthetic_browser):
    client, exchange = synthetic_browser
    first = client.get("/dashboard/login", follow_redirects=False)
    second = client.get("/dashboard/login", follow_redirects=False)
    assert cookies(first)["pkce_verifier"].value != cookies(second)["pkce_verifier"].value
    assert set(client.cookies.keys()) == {"pkce_verifier"}
    exchange["status"] = 400
    denied = client.get("/dashboard/callback?code=synthetic-code", follow_redirects=False)
    assert denied.status_code == 400
    assert not cookies(denied)
    assert set(client.cookies.keys()) == {"pkce_verifier"}
    assert client.get("/private").status_code == 401


def test_canceled_entra_login_leaves_only_short_lived_handshake_cookie(synthetic_browser):
    client, exchange = synthetic_browser
    client.get("/dashboard/login", follow_redirects=False)
    response = client.get("/dashboard/callback?error=access_denied", follow_redirects=False)
    assert response.status_code == 400
    assert not cookies(response)
    assert set(client.cookies.keys()) == {"pkce_verifier"}
    assert exchange["calls"] == []


def test_api_key_mode_uses_only_csrf_and_thirty_day_session(synthetic_browser, monkeypatch):
    client, _ = synthetic_browser
    monkeypatch.delenv("ENTRA_TENANT_ID")
    monkeypatch.delenv("ENTRA_CLIENT_ID")
    monkeypatch.setenv("API_KEY", "synthetic-local-key")
    reset_settings_cache()
    reset_auth_provider_cache()
    form = client.get("/dashboard/login")
    assert set(cookies(form)) == {"__Host-jc_login_csrf"}
    assert_security_cookie(cookies(form)["__Host-jc_login_csrf"], seconds=600, same_site="strict")
    token = re.search(r'name="csrf_token" value="([^"]+)"', form.text).group(1)
    signed_in = client.post("/dashboard/login", data={
        "api_key": "synthetic-local-key", "csrf_token": token,
    }, headers={"Origin": "https://testserver"}, follow_redirects=False)
    assert signed_in.status_code == 303
    assert set(cookies(signed_in)) == {"__Host-jc_login_csrf", "jc_session"}
    assert_security_cookie(cookies(signed_in)["jc_session"], seconds=30 * 24 * 60 * 60)
    assert set(client.cookies.keys()) == {"jc_session"}
    assert client.get("/private").status_code == 200
    logout = client.post("/logout", follow_redirects=False)
    assert logout.headers["location"] == "/"
    assert not client.cookies


def test_oura_state_only_exists_for_requested_connection_and_clears_on_return(synthetic_browser, monkeypatch):
    client, _ = synthetic_browser
    client.cookies.set("jc_session", "synthetic-access-token", domain="testserver.local", path="/")
    monkeypatch.setattr(oura.oura, "oura_configured", lambda: True)
    monkeypatch.setattr(oura.oura, "oura_authorize_url", lambda state, redirect: "https://cloud.ouraring.com/oauth/authorize")
    connect = client.get("/dashboard/oura/connect", follow_redirects=False)
    assert connect.status_code == 302
    assert set(cookies(connect)) == {"oura_state"}
    assert_security_cookie(cookies(connect)["oura_state"], seconds=600)
    canceled = client.get("/dashboard/oura/callback?error=access_denied", follow_redirects=False)
    assert canceled.headers["location"] == "/app/settings?oura=error"
    assert cookies(canceled)["oura_state"]["max-age"] == "0"
    assert set(client.cookies.keys()) == {"jc_session"}


def test_oura_success_clears_state_without_extra_cookies(synthetic_browser, monkeypatch):
    client, _ = synthetic_browser
    client.cookies.set("jc_session", "synthetic-access-token", domain="testserver.local", path="/")
    monkeypatch.setattr(oura.oura, "oura_configured", lambda: True)
    monkeypatch.setattr(oura.oura, "oura_authorize_url", lambda state, redirect: "https://cloud.ouraring.com/oauth/authorize")
    monkeypatch.setattr(oura.oura, "exchange_code_for_tokens", lambda *_: {"access_token": "synthetic-oura-token"})
    saved = []
    monkeypatch.setattr(oura.oura, "save_oura_tokens", saved.append)
    monkeypatch.setattr(oura.oura, "sync_oura", lambda: None)
    start = client.get("/dashboard/oura/connect", follow_redirects=False)
    state = cookies(start)["oura_state"].value
    returned = client.get(f"/dashboard/oura/callback?code=synthetic-code&state={state}", follow_redirects=False)
    assert returned.headers["location"] == "/app/settings?oura=connected"
    assert set(cookies(returned)) == {"oura_state"}
    assert cookies(returned)["oura_state"]["max-age"] == "0"
    assert set(client.cookies.keys()) == {"jc_session"}
    assert saved == [{"access_token": "synthetic-oura-token"}]


def test_oura_expired_signin_leaves_state_to_its_short_expiry(synthetic_browser, monkeypatch):
    client, _ = synthetic_browser
    client.cookies.set("jc_session", "synthetic-access-token", domain="testserver.local", path="/")
    monkeypatch.setattr(oura.oura, "oura_configured", lambda: True)
    monkeypatch.setattr(oura.oura, "oura_authorize_url", lambda state, redirect: "https://cloud.ouraring.com/oauth/authorize")
    start = client.get("/dashboard/oura/connect", follow_redirects=False)
    assert_security_cookie(cookies(start)["oura_state"], seconds=600)
    del client.cookies["jc_session"]
    response = client.get("/dashboard/oura/callback?error=access_denied", follow_redirects=False)
    assert response.status_code == 401
    assert not cookies(response)
    assert set(client.cookies.keys()) == {"oura_state"}


@pytest.mark.parametrize("path", ["/", "/why", "/setup", "/architecture", "/login", "/privacy", "/terms"])
def test_public_pages_do_not_set_app_owned_cookies(http_client_authed, path):
    response = http_client_authed.get(path)
    assert response.status_code == 200
    assert not cookies(response)
    assert not http_client_authed.cookies
