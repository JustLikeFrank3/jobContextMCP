"""Browser policy at the app boundary, independent of the deployment ingress.

The public pages have static, developer-owned templates. Their inline CSS is
allowlisted by content hash *before* any request values are rendered. Never
hash an arbitrary response body here: doing so would bless injected content.
Legacy authenticated HTML retains only the framing/base/object protections
until its inline handlers and generated document styles are migrated.
"""
from __future__ import annotations

import base64
from functools import lru_cache
import hashlib
from html.parser import HTMLParser

from starlette.datastructures import MutableHeaders


_BASE_POLICY = "base-uri 'self'; object-src 'none'; frame-ancestors 'self'"
_SOURCES = (
    "default-src 'none'; script-src 'self'; "
    "img-src 'self' data:; font-src 'self'; "
    "connect-src 'self'; frame-src 'self'; "
    "form-action 'self' https://login.microsoftonline.com"
)


def _hash_source(value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).digest()
    return "'sha256-" + base64.b64encode(digest).decode("ascii") + "'"


class _TemplateStyles(HTMLParser):
    """Collect only styles from a trusted template, never from a request."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks: set[str] = set()
        self._style: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        if tag == "style":
            self._style = []

    def handle_data(self, data):
        if self._style is not None:
            self._style.append(data)

    def handle_endtag(self, tag):
        if tag == "style" and self._style is not None:
            self.blocks.add(_hash_source("".join(self._style)))
            self._style = None


def _strict_policy(trusted_template: str = "") -> str:
    styles = _TemplateStyles()
    styles.feed(trusted_template)
    # Public templates use classes, never style attributes. Hash only authored
    # style blocks; do not relax the policy with unsafe-inline/unsafe-hashes.
    sources = ["'self'", *sorted(styles.blocks)]
    return f"{_BASE_POLICY}; {_SOURCES}; style-src {' '.join(sources)}"


@lru_cache(maxsize=1)
def _public_policies() -> dict[str, str]:
    from transport.http.routes.architecture import architecture_html
    from transport.http.routes.landing import landing_html
    from transport.http.routes.login_page import login_html
    from transport.http.routes.oauth import _LOGGED_OUT_HTML
    from transport.http.routes.privacy import privacy_html
    from transport.http.routes.setup import setup_html
    from transport.http.routes.terms import terms_html
    from transport.http.routes.why import why_html

    # These functions return source-controlled templates. login_html's only
    # interpolation is a URL-escaped link; no request value enters this map.
    pages = {
        "/": landing_html(), "/architecture": architecture_html(),
        "/login": login_html(), "/privacy": privacy_html(),
        "/setup": setup_html(), "/terms": terms_html(), "/why": why_html(),
        "/dashboard/login": "", "/dashboard/callback": "",
        "/logged-out": _LOGGED_OUT_HTML,
    }
    return {path: _strict_policy(template) for path, template in pages.items()}


def content_security_policy(path: str) -> str:
    if path == "/app" or path.startswith("/app/"):
        return _strict_policy()
    return _public_policies().get(path, _BASE_POLICY)


class SecurityHeadersMiddleware:
    """Pure ASGI: preserve streaming/SSE bodies and authentication responses."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers.setdefault("Content-Security-Policy", content_security_policy(scope["path"]))
                # SAMEORIGIN intentionally preserves the app's document and
                # resume-template preview iframes, unlike DENY.
                headers.setdefault("X-Frame-Options", "SAMEORIGIN")
                headers.setdefault("X-Content-Type-Options", "nosniff")
                headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
            await send(message)

        await self.app(scope, receive, send_with_headers)
