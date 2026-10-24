"""API-key browser login requires a page challenge, not ambient credentials.

Entra's PKCE GET/callback flow and API bearer authentication are not changed.
All requests here use in-process TestClient and synthetic credentials.
"""
import re

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from transport.http.app import create_app
from transport.http.routes.dashboard import login


ORIGIN = {"Origin": "http://testserver"}


def challenge(client, **kwargs):
    response = client.get("/dashboard/login", **kwargs)
    assert response.status_code == 200
    token = re.search(r'name="csrf_token" value="([^"]+)"', response.text).group(1)
    return response, token


def submit(client, token, *, headers=ORIGIN, **data):
    return client.post(
        "/dashboard/login",
        data={"api_key": "test-key", "csrf_token": token, **data},
        headers=headers, follow_redirects=False,
    )


def test_challenge_is_random_private_and_non_cacheable(http_client_authed):
    page, first = challenge(http_client_authed)
    assert re.fullmatch(r"[A-Za-z0-9_-]{43}", first)
    assert page.cookies["jc_login_csrf"] == first
    assert page.headers["cache-control"] == "no-store"
    cookie = page.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie
    assert "Path=/" in cookie and "Max-Age=600" in cookie and "Domain=" not in cookie
    assert '<link rel="stylesheet" href="/static/dashboard-login.css"' in page.text
    assert "<style" not in page.text and "style=" not in page.text
    _, second = challenge(http_client_authed)
    assert first != second


@pytest.mark.parametrize("token", ["", "wrong", "a" * 43, "é" * 43, "a" * 10000])
def test_missing_wrong_and_malformed_form_tokens_rejected(http_client_authed, token):
    challenge(http_client_authed)
    response = submit(http_client_authed, token)
    assert response.status_code == 403
    assert "jc_session" not in response.cookies


def test_token_without_browser_cookie_rejected(http_client_authed):
    _, token = challenge(http_client_authed)
    http_client_authed.cookies.clear()
    assert submit(http_client_authed, token).status_code == 403


def test_missing_form_field_rejected(http_client_authed):
    challenge(http_client_authed)
    response = http_client_authed.post(
        "/dashboard/login", data={"api_key": "test-key"}, headers=ORIGIN,
    )
    assert response.status_code == 403


def test_challenge_from_another_browser_is_rejected(http_client_authed):
    _, original = challenge(http_client_authed)
    with TestClient(http_client_authed.app) as other:
        _, unrelated = challenge(other)
        assert submit(other, original).status_code == 403
        assert submit(other, unrelated).status_code == 303


@pytest.mark.parametrize("headers", [
    {},
    {"Origin": "https://evil.example"},
    {"Origin": "http://testserver.evil.example"},
    {"Origin": "https://testserver"},
    {"Origin": "null"},
    {"Origin": "http://["},
    {"Origin": "http://user@testserver"},
    {"Referer": "http://evil.example/login"},
    {**ORIGIN, "Sec-Fetch-Site": "same-site"},
    {**ORIGIN, "Sec-Fetch-Site": "cross-site"},
    {**ORIGIN, "Sec-Fetch-Site": "none"},
    {"Origin": "http://evil.example", "Sec-Fetch-Site": "same-origin"},
])
def test_hostile_or_missing_browser_provenance_rejected(http_client_authed, headers):
    _, token = challenge(http_client_authed)
    assert submit(http_client_authed, token, headers=headers).status_code == 403


@pytest.mark.parametrize("headers", [
    ORIGIN,
    {"Sec-Fetch-Site": "same-origin"},
    {"Referer": "http://testserver/dashboard/login?next=/app"},
    {**ORIGIN, "Sec-Fetch-Site": "same-origin"},
])
def test_valid_same_origin_submit_keeps_safe_destination(http_client_authed, headers):
    _, token = challenge(http_client_authed)
    response = submit(http_client_authed, token, headers=headers, next="/oauth/authorize?state=test")
    assert response.status_code == 303
    assert response.headers["location"] == "/oauth/authorize?state=test"
    assert response.cookies["jc_session"] == "test-key"
    assert "jc_login_csrf" not in http_client_authed.cookies
    assert response.headers["cache-control"] == "no-store"


def test_old_form_and_repeat_submit_fail_then_reload_recovers(http_client_authed):
    _, old = challenge(http_client_authed)
    _, current = challenge(http_client_authed)
    assert submit(http_client_authed, old).status_code == 403
    assert submit(http_client_authed, current).status_code == 303
    assert submit(http_client_authed, current).status_code == 403
    _, fresh = challenge(http_client_authed)
    assert submit(http_client_authed, fresh).status_code == 303


def test_rejected_csrf_never_checks_login_credential(http_client_authed, monkeypatch):
    def forbidden(_credential):
        pytest.fail("login credential checked before CSRF validation")
    monkeypatch.setattr(login.get_auth_provider(), "authenticate_login", forbidden)
    assert submit(http_client_authed, "").status_code == 403


def test_auth_disabled_keeps_no_login_required_flow(http_client_noauth):
    page = http_client_noauth.get("/dashboard/login")
    assert "Authentication disabled" in page.text
    assert "csrf_token" not in page.text and not page.cookies
    response = submit(http_client_noauth, "", headers={})
    assert response.status_code == 303
    assert "jc_session" not in response.cookies


def test_https_uses_host_cookie_not_injectable_http_cookie(http_client_authed):
    with TestClient(http_client_authed.app, base_url="https://testserver") as secure:
        page, token = challenge(secure)
        cookie = page.headers["set-cookie"]
        assert "__Host-jc_login_csrf=" in cookie and "Secure" in cookie
        assert "Path=/" in cookie and "Domain=" not in cookie
        assert submit(secure, token, headers={"Origin": "https://testserver"}).status_code == 303
        secure.cookies.clear()
        secure.cookies.set("jc_login_csrf", token)
        assert submit(secure, token, headers={"Origin": "https://testserver"}).status_code == 403


def test_tls_proxy_cookie_and_origin_policy(http_client_authed):
    page, token = challenge(http_client_authed, headers={"X-Forwarded-Proto": "https"})
    assert "__Host-jc_login_csrf=" in page.headers["set-cookie"]
    assert "Secure" in page.headers["set-cookie"]
    # The browser sees HTTPS; the trusted ingress forwards HTTP to the app.
    request = Request({
        "type": "http", "method": "POST", "path": "/dashboard/login", "scheme": "http",
        "headers": [(b"host", b"testserver"), (b"origin", b"https://testserver"),
                    (b"x-forwarded-proto", b"https"),
                    (b"cookie", f"__Host-jc_login_csrf={token}".encode())],
    })
    login._validate_login_csrf(request, token)
