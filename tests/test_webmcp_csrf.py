"""CSRF guard on cookie-authenticated /mcp requests.

The jc_session cookie is an ambient credential: a browser attaches it to any
site's request. The WebMCP bridge in the SPA authenticates its same-origin
/mcp calls with it — which is exactly the shape a hostile page's
fetch('https://jobcontext.ai/mcp', {credentials:'include'}) would have, and a
bare POST needs no CORS preflight. UserDataContextMiddleware therefore drops
the cookie (never the bearer header) on /mcp requests that a browser marks as
cross-site, so they fall through to the normal 401 challenge.

Runs in API-key mode (http_client_authed: API_KEY=test-key) — the guard sits
in front of provider resolution, so which provider validates the cookie is
irrelevant to what's under test.
"""

from __future__ import annotations


COOKIE = {"jc_session": "test-key"}


def _post_mcp(client, headers=None, cookies=COOKIE):
    # No MCP app is mounted in these tests, so a request that SURVIVES auth
    # 404s at routing. 401 = the guard (or missing auth) rejected it.
    return client.post("/mcp", headers=headers or {}, cookies=cookies)


class TestCrossSiteCookieRejected:
    def test_sec_fetch_site_cross_site_is_401(self, http_client_authed):
        r = _post_mcp(http_client_authed, {"Sec-Fetch-Site": "cross-site"})
        assert r.status_code == 401

    def test_sec_fetch_site_same_site_is_401(self, http_client_authed):
        """Sibling subdomains are same-site but NOT same-origin — the SPA is
        served from the API's own origin, so nothing legitimate sends this."""
        r = _post_mcp(http_client_authed, {"Sec-Fetch-Site": "same-site"})
        assert r.status_code == 401

    def test_origin_mismatch_without_sec_fetch_site_is_401(self, http_client_authed):
        r = _post_mcp(http_client_authed, {"Origin": "https://evil.example"})
        assert r.status_code == 401

    def test_rejection_is_the_standard_bearer_challenge(self, http_client_authed):
        """The refusal must read as 'authenticate properly', not a dead end —
        a legitimate non-browser client that happens to send a cookie should
        be steered to bearer auth by WWW-Authenticate."""
        r = _post_mcp(http_client_authed, {"Sec-Fetch-Site": "cross-site"})
        assert "WWW-Authenticate" in r.headers


class TestLegitimateSendersUnaffected:
    def test_same_origin_browser_cookie_passes_auth(self, http_client_authed):
        # 404: authenticated, then unrouted (no MCP app mounted in tests).
        r = _post_mcp(http_client_authed, {"Sec-Fetch-Site": "same-origin"})
        assert r.status_code == 404

    def test_matching_origin_header_passes_auth(self, http_client_authed):
        r = _post_mcp(http_client_authed, {"Origin": "http://testserver"})
        assert r.status_code == 404

    def test_non_browser_cookie_sender_passes_auth(self, http_client_authed):
        """No Sec-Fetch-Site and no Origin = not a browser = not CSRF-able."""
        r = _post_mcp(http_client_authed)
        assert r.status_code == 404

    def test_bearer_credential_ignores_cross_site_marking(self, http_client_authed):
        """Bearer tokens are attached deliberately by the sender, never
        ambiently by a browser — the guard must not touch them."""
        r = _post_mcp(
            http_client_authed,
            {"Sec-Fetch-Site": "cross-site", "Authorization": "Bearer test-key"},
            cookies={},
        )
        assert r.status_code == 404

    def test_cross_site_cookie_on_non_mcp_path_keeps_existing_behavior(self, http_client_authed):
        """The guard is scoped to /mcp — dashboard routes keep their current
        cookie semantics (tightening those is a separate decision)."""
        r = http_client_authed.get(
            "/api/dashboard/me",
            headers={"Sec-Fetch-Site": "cross-site"},
            cookies=COOKIE,
        )
        assert r.status_code != 401
