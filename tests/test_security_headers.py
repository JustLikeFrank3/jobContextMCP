"""Public-page CSP and universal framing headers must not alter auth/streaming."""
import asyncio
from html.parser import HTMLParser

import pytest

from transport.http.security_headers import (
    SecurityHeadersMiddleware, _hash_source, _strict_policy, content_security_policy,
)


class _Resources(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.style_blocks = []
        self.style_attrs = []
        self.scripts = []
        self._style = None

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if "style" in values:
            self.style_attrs.append(values["style"])
        if tag == "style":
            self._style = []
        if tag == "script":
            self.scripts.append(values.get("src"))

    def handle_data(self, data):
        if self._style is not None:
            self._style.append(data)

    def handle_endtag(self, tag):
        if tag == "style":
            self.style_blocks.append("".join(self._style))
            self._style = None


@pytest.mark.parametrize("path", [
    "/", "/why", "/setup", "/architecture", "/login", "/privacy", "/terms",
    "/dashboard/login", "/logged-out",
])
def test_public_pages_allow_authored_styles_only(http_client_authed, path):
    response = http_client_authed.get(path)
    assert response.status_code == 200
    policy = response.headers["content-security-policy"]
    assert "default-src 'none'" in policy
    assert "script-src 'self'" in policy
    assert "'unsafe-inline'" not in policy
    assert "'unsafe-eval'" not in policy
    assert "'unsafe-hashes'" not in policy
    resources = _Resources()
    resources.feed(response.text)
    assert not resources.style_attrs
    for style in resources.style_blocks:
        assert _hash_source(style) in policy
    assert not resources.scripts  # architecture uses inert first-party diagrams
    assert _hash_source("body { display:none }") not in policy


def test_reflected_next_never_changes_policy(http_client_authed):
    normal = http_client_authed.get("/login")
    malicious = http_client_authed.get("/login", params={"next": '</a><script>alert(1)</script>'})
    assert normal.headers["content-security-policy"] == malicious.headers["content-security-policy"]
    assert "<script>" not in malicious.text


def test_style_attributes_never_add_hash_allowances():
    policy = _strict_policy('<p style="display:none">Hidden</p>')
    assert "'unsafe-hashes'" not in policy
    assert _hash_source("display:none") not in policy


@pytest.mark.parametrize("path,status", [
    ("/health", 200), ("/api/jobs", 401), ("/static/dashboard-login.css", 200),
    ("/dashboard/callback?error=access_denied", 400),
])
def test_headers_on_public_static_auth_failures_and_callback(http_client_authed, path, status):
    response = http_client_authed.get(path, follow_redirects=False)
    assert response.status_code == status
    assert response.headers["x-frame-options"] == "SAMEORIGIN"
    assert "frame-ancestors 'self'" in response.headers["content-security-policy"]
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    if status == 401:
        assert "WWW-Authenticate" in response.headers


def test_spa_policy_and_legacy_preview_compatibility():
    assert "script-src 'self'" in content_security_policy("/app/pipeline")
    assert "frame-src 'self'" in content_security_policy("/app")
    assert "https://login.microsoftonline.com" in content_security_policy("/app")
    assert "'unsafe-hashes'" not in content_security_policy("/app")
    legacy = content_security_policy("/dashboard/pipeline")
    assert "frame-ancestors 'self'" in legacy
    # Generated document/legacy flows are not falsely claimed to have strict
    # source CSP. In particular don't block external OAuth consent redirects.
    assert "form-action" not in legacy
    assert "script-src" not in legacy


def test_asgi_headers_preserve_streaming_body_and_existing_policy():
    async def run():
        messages = []

        async def application(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": [
                (b"content-security-policy", b"default-src 'none'"),
                (b"content-type", b"text/event-stream"),
            ]})
            await send({"type": "http.response.body", "body": b"data: one\n\n", "more_body": True})
            await send({"type": "http.response.body", "body": b"data: two\n\n", "more_body": False})

        async def send(message):
            messages.append(message)

        await SecurityHeadersMiddleware(application)({"type": "http", "path": "/mcp"}, None, send)
        return messages

    messages = asyncio.run(run())
    headers = dict(messages[0]["headers"])
    assert headers[b"content-security-policy"] == b"default-src 'none'"
    assert [m["body"] for m in messages[1:]] == [b"data: one\n\n", b"data: two\n\n"]
    assert messages[1]["more_body"] is True
    assert messages[2]["more_body"] is False


def test_non_http_scopes_pass_through():
    seen = []

    async def application(scope, receive, send):
        seen.append(scope["type"])

    asyncio.run(SecurityHeadersMiddleware(application)({"type": "lifespan"}, None, None))
    assert seen == ["lifespan"]
