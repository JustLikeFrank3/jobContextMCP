"""Tests for the dashboard browser-auth routes.

Target: transport/http/routes/dashboard/login.py — the API-key form that sets
an HTTP-only `jc_session` cookie so mobile browsers can reach protected
dashboard routes without manually sending Authorization headers. Shipped with
zero coverage.

Covers:
  - GET  /dashboard/login   (auth-disabled notice vs. real form)
  - POST /dashboard/login   (wrong key, correct key + cookie, disabled passthrough)
  - POST /dashboard/logout  (clears the session cookie)
  - cookie issued by login actually authorizes a protected route end-to-end
  - _safe_next open-redirect guard
"""

from transport.http.routes.dashboard import login as lg


# ──────────────────────────────────────────────────────────────────────────────
# GET /dashboard/login
# ──────────────────────────────────────────────────────────────────────────────

class TestLoginPage:
    def test_login_page_shows_disabled_notice_when_no_key(self, http_client_noauth):
        r = http_client_noauth.get("/dashboard/login")
        assert r.status_code == 200
        assert "Authentication disabled" in r.text

    def test_login_page_renders_form_when_auth_enabled(self, http_client_authed):
        r = http_client_authed.get("/dashboard/login")
        assert r.status_code == 200
        assert "Dashboard Login" in r.text
        assert 'name="api_key"' in r.text

    def test_login_page_preserves_safe_next(self, http_client_authed):
        r = http_client_authed.get("/dashboard/login", params={"next": "/dashboard/pipeline"})
        assert r.status_code == 200
        assert "/dashboard/pipeline" in r.text


# ──────────────────────────────────────────────────────────────────────────────
# POST /dashboard/login
# ──────────────────────────────────────────────────────────────────────────────

class TestLoginSubmit:
    def test_wrong_key_redirects_back_to_login(self, http_client_authed):
        r = http_client_authed.post(
            "/dashboard/login",
            data={"api_key": "nope", "next": "/dashboard"},
            follow_redirects=False,
        )
        assert r.status_code == 303
        assert "/dashboard/login" in r.headers["location"]
        # No session cookie issued on failure.
        assert "jc_session" not in r.cookies

    def test_correct_key_sets_cookie_and_redirects(self, http_client_authed):
        r = http_client_authed.post(
            "/dashboard/login",
            data={"api_key": "test-key", "next": "/dashboard/pipeline"},
            follow_redirects=False,
        )
        assert r.status_code == 303
        assert r.headers["location"] == "/dashboard/pipeline"
        assert r.cookies.get("jc_session") == "test-key"

    def test_disabled_auth_passes_through(self, http_client_noauth):
        r = http_client_noauth.post(
            "/dashboard/login",
            data={"api_key": "anything", "next": "/dashboard"},
            follow_redirects=False,
        )
        assert r.status_code == 303
        assert r.headers["location"] == "/dashboard"

    def test_open_redirect_next_is_sanitized(self, http_client_authed):
        r = http_client_authed.post(
            "/dashboard/login",
            data={"api_key": "test-key", "next": "https://evil.example.com"},
            follow_redirects=False,
        )
        assert r.status_code == 303
        # External next must collapse to the dashboard root, never the evil host.
        assert r.headers["location"] == "/dashboard"

    def test_cookie_from_login_authorizes_protected_route(self, http_client_authed):
        login = http_client_authed.post(
            "/dashboard/login",
            data={"api_key": "test-key", "next": "/dashboard"},
            follow_redirects=False,
        )
        token = login.cookies.get("jc_session")
        assert token == "test-key"
        r = http_client_authed.get(
            "/dashboard/pipeline/data", cookies={"jc_session": token}
        )
        assert r.status_code == 200


# ──────────────────────────────────────────────────────────────────────────────
# POST /dashboard/logout
# ──────────────────────────────────────────────────────────────────────────────

class TestLogout:
    def test_logout_redirects_to_login_and_clears_cookie(self, http_client_authed):
        r = http_client_authed.post("/dashboard/logout", follow_redirects=False)
        assert r.status_code == 303
        assert "/dashboard/login" in r.headers["location"]
        # Set-Cookie must expire the session cookie.
        set_cookie = r.headers.get("set-cookie", "")
        assert "jc_session=" in set_cookie


# ──────────────────────────────────────────────────────────────────────────────
# _safe_next — pure guard
# ──────────────────────────────────────────────────────────────────────────────

class TestSafeNext:
    def test_allows_dashboard_paths(self):
        assert lg._safe_next("/dashboard/pipeline") == "/dashboard/pipeline"

    def test_blocks_external_url(self):
        assert lg._safe_next("https://evil.example.com") == "/dashboard"

    def test_blocks_scheme_relative_url(self):
        assert lg._safe_next("//evil.example.com") == "/dashboard"

    def test_none_defaults_to_dashboard_root(self):
        assert lg._safe_next(None) == "/dashboard"

    def test_non_dashboard_path_rejected(self):
        assert lg._safe_next("/etc/passwd") == "/dashboard"
