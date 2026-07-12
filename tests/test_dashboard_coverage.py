import asyncio
import datetime as dt
import importlib
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from transport.http.app import create_app
from transport.http.config import reset_settings_cache
from transport.http.routes.dashboard import api as dashboard_api_routes
from transport.http.routes.dashboard import api_keys as api_keys_routes
from transport.http.routes.dashboard import assets as assets_routes
from transport.http.routes.dashboard import digest as digest_routes
from transport.http.routes.dashboard import home as home_routes
from transport.http.routes.dashboard import interviews as interviews_routes
from transport.http.routes.dashboard import login as login_routes
from transport.http.routes.dashboard import materials as materials_routes
from transport.http.routes.dashboard import people as people_routes
from transport.http.routes.dashboard import pipeline as pipeline_routes
from transport.http.routes.dashboard import settings as settings_routes
from transport.http.security import User, reset_auth_provider_cache


@pytest.fixture(autouse=True)
def _reset_http_caches():
    reset_settings_cache()
    reset_auth_provider_cache()
    yield
    reset_settings_cache()
    reset_auth_provider_cache()


class TestHttpMainCoverage:
    def test_main_module_exposes_health_endpoint(self, monkeypatch):
        monkeypatch.delenv("API_KEY", raising=False)
        import transport.http.main as main_module

        main_module = importlib.reload(main_module)

        with TestClient(main_module.app) as client:
            response = client.get("/health")

        assert response.status_code == 200
        assert response.json()["service"] == "jobContextMCP"

    def test_main_uses_bound_host_and_port(self, monkeypatch):
        import transport.http.main as main_module

        calls = {}
        monkeypatch.setattr(
            main_module,
            "get_settings",
            lambda: SimpleNamespace(bind_host="127.0.0.1", port=4242),
        )
        monkeypatch.setattr(
            main_module.uvicorn,
            "run",
            lambda *args, **kwargs: calls.update({"args": args, "kwargs": kwargs}),
        )

        main_module.main()

        assert calls == {
            "args": ("transport.http.main:app",),
            "kwargs": {
                "host": "127.0.0.1",
                "port": 4242,
                "reload": False,
                "log_level": "info",
            },
        }


class TestDashboardLoginCoverage:
    def test_login_page_shows_auth_disabled_message(self, http_client_noauth):
        response = http_client_noauth.get("/dashboard/login")

        assert response.status_code == 200
        assert "Authentication disabled" in response.text
        assert "Open dashboard" in response.text

    def test_login_page_renders_form_and_sanitizes_next(self, http_client_authed):
        response = http_client_authed.get("/dashboard/login?next=/not-dashboard")

        assert response.status_code == 200
        assert 'method="post" action="/dashboard/login"' in response.text
        assert 'name="next" value="/app"' in response.text
        assert "Enter your API key" in response.text

    def test_login_page_redirects_to_entra_with_pkce(self, monkeypatch, isolated_server):
        monkeypatch.setenv("ENTRA_TENANT_ID", "tenant-123")
        monkeypatch.setenv("ENTRA_CLIENT_ID", "client-456")
        monkeypatch.delenv("API_KEY", raising=False)
        reset_settings_cache()
        reset_auth_provider_cache()

        with TestClient(create_app(), base_url="https://testserver") as client:
            response = client.get(
                "/dashboard/login?next=/dashboard/settings",
                follow_redirects=False,
            )

        assert response.status_code == 302
        assert response.headers["location"].startswith(
            "https://login.microsoftonline.com/tenant-123/oauth2/v2.0/authorize?"
        )
        assert "code_challenge_method=S256" in response.headers["location"]
        assert response.cookies.get("pkce_verifier")
        assert "pkce_verifier=" in response.headers["set-cookie"]
        assert "Secure" in response.headers["set-cookie"]

    def test_login_submit_rejects_invalid_key(self, http_client_authed):
        response = http_client_authed.post(
            "/dashboard/login",
            data={"api_key": "wrong", "next": "/offsite"},
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert response.headers["location"] == "/dashboard/login?next=/app"

    def test_login_submit_sets_session_cookie_on_success(self, http_client_authed):
        response = http_client_authed.post(
            "/dashboard/login",
            data={"api_key": "test-key", "next": "/dashboard/settings"},
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert response.headers["location"] == "/dashboard/settings"
        assert "jc_session=test-key" in response.headers["set-cookie"]
        assert "HttpOnly" in response.headers["set-cookie"]

    def test_logout_clears_cookie_and_redirects_to_login(self, http_client_authed):
        response = http_client_authed.post("/dashboard/logout", follow_redirects=False)

        assert response.status_code == 303
        assert response.headers["location"] == "/dashboard/login"
        assert "jc_session=" in response.headers["set-cookie"]
        assert "Max-Age=0" in response.headers["set-cookie"]

    def test_callback_renders_error_page(self, http_client_noauth):
        response = http_client_noauth.get("/dashboard/callback?error=access_denied")

        assert response.status_code == 400
        assert "Login failed" in response.text
        assert "access_denied" in response.text

    def test_callback_redirects_when_code_or_verifier_is_missing(self, http_client_noauth):
        response = http_client_noauth.get(
            "/dashboard/callback?code=abc123",
            follow_redirects=False,
        )

        assert response.status_code == 302
        assert response.headers["location"] == "/dashboard/login"

    def test_callback_requires_client_secret(self, monkeypatch, http_client_noauth):
        monkeypatch.setenv("ENTRA_TENANT_ID", "tenant-123")
        monkeypatch.setenv("ENTRA_CLIENT_ID", "client-456")
        monkeypatch.delenv("ENTRA_CLIENT_SECRET", raising=False)
        http_client_noauth.cookies.set("pkce_verifier", "verifier-123")

        response = http_client_noauth.get("/dashboard/callback?code=abc123")

        assert response.status_code == 500
        assert "Server auth not configured" in response.text

    def test_callback_renders_token_exchange_failure(self, monkeypatch, http_client_noauth):
        monkeypatch.setenv("ENTRA_TENANT_ID", "tenant-123")
        monkeypatch.setenv("ENTRA_CLIENT_ID", "client-456")
        monkeypatch.setenv("ENTRA_CLIENT_SECRET", "secret-789")
        http_client_noauth.cookies.set("pkce_verifier", "verifier-123")

        class FakeResponse:
            status_code = 400
            text = "bad token exchange"

            def json(self):
                return {}

        class FakeAsyncClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def post(self, url, data):
                return FakeResponse()

        monkeypatch.setattr(login_routes.httpx, "AsyncClient", lambda: FakeAsyncClient())

        response = http_client_noauth.get("/dashboard/callback?code=abc123")

        assert response.status_code == 400
        assert "Token exchange failed" in response.text
        assert "bad token exchange" in response.text

    def test_callback_sets_session_cookie_after_successful_exchange(self, monkeypatch, http_client_noauth):
        monkeypatch.setenv("ENTRA_TENANT_ID", "tenant-123")
        monkeypatch.setenv("ENTRA_CLIENT_ID", "client-456")
        monkeypatch.setenv("ENTRA_CLIENT_SECRET", "secret-789")
        http_client_noauth.cookies.set("pkce_verifier", "verifier-123")

        captured = {}

        class FakeResponse:
            status_code = 200
            text = "ok"

            def json(self):
                return {"access_token": "entra-access-token"}

        class FakeAsyncClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def post(self, url, data):
                captured["url"] = url
                captured["data"] = data
                return FakeResponse()

        monkeypatch.setattr(login_routes.httpx, "AsyncClient", lambda: FakeAsyncClient())

        response = http_client_noauth.get(
            "/dashboard/callback?code=abc123&state=/dashboard/settings",
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert response.headers["location"] == "/dashboard/settings"
        assert "jc_session=entra-access-token" in response.headers["set-cookie"]
        assert "pkce_verifier=" in response.headers["set-cookie"]
        assert captured["url"].endswith("/oauth2/v2.0/token")
        assert captured["data"]["code_verifier"] == "verifier-123"


class TestDashboardSettingsCoverage:
    def test_user_config_path_rejects_escape(self, monkeypatch):
        monkeypatch.setattr("lib.user_context.get_data_folder_override", lambda: settings_routes.Path("/safe/root"))
        monkeypatch.setattr(settings_routes, "_CONFIG_FILENAME", "../escape.json")

        with pytest.raises(HTTPException) as exc:
            settings_routes._user_config_path(User(id="user-1", name="Test User"))

        assert exc.value.status_code == 400

    def test_settings_page_renders_saved_flash_with_existing_key(
        self,
        http_client_noauth,
        isolated_server,
        monkeypatch,
    ):
        config_path = isolated_server / "data" / "config.json"
        config_path.write_text(json.dumps({"openai_api_key": "sk-existing"}), encoding="utf-8")
        monkeypatch.setattr(
            "lib.user_context.get_data_folder_override",
            lambda: isolated_server / "data",
        )

        response = http_client_noauth.get("/dashboard/settings?saved=1")

        assert response.status_code == 200
        assert "Settings saved" in response.text
        assert "API key configured" in response.text
        assert "Remove key" in response.text

    def test_settings_save_key_persists_config(self, http_client_noauth, isolated_server, monkeypatch):
        config_path = isolated_server / "data" / "config.json"
        monkeypatch.setattr(
            "lib.user_context.get_data_folder_override",
            lambda: isolated_server / "data",
        )

        response = http_client_noauth.post(
            "/dashboard/settings/ai-key",
            data={"openai_key": "sk-test-value", "action": "save"},
        )

        assert response.status_code == 200
        assert "OpenAI API key saved" in response.text
        assert json.loads(config_path.read_text(encoding="utf-8"))["openai_api_key"] == "sk-test-value"

    def test_settings_clear_key_removes_existing_value(self, http_client_noauth, isolated_server, monkeypatch):
        config_path = isolated_server / "data" / "config.json"
        config_path.write_text(json.dumps({"openai_api_key": "sk-existing", "theme": "dark"}), encoding="utf-8")
        monkeypatch.setattr(
            "lib.user_context.get_data_folder_override",
            lambda: isolated_server / "data",
        )

        response = http_client_noauth.post(
            "/dashboard/settings/ai-key",
            data={"openai_key": "", "action": "clear"},
        )

        assert response.status_code == 200
        assert "API key removed" in response.text
        saved = json.loads(config_path.read_text(encoding="utf-8"))
        assert "openai_api_key" not in saved
        assert saved["theme"] == "dark"

    def test_settings_rejects_invalid_openai_key(self, http_client_noauth, isolated_server, monkeypatch):
        monkeypatch.setattr(
            "lib.user_context.get_data_folder_override",
            lambda: isolated_server / "data",
        )

        response = http_client_noauth.post(
            "/dashboard/settings/ai-key",
            data={"openai_key": "not-a-real-key", "action": "save"},
        )

        assert response.status_code == 200
        assert "valid OpenAI key" in response.text
        assert "sk-" in response.text

    def test_settings_handles_invalid_json_config(self, isolated_server):
        config_path = isolated_server / "data" / "config.json"
        config_path.write_text("{bad json", encoding="utf-8")

        assert settings_routes._read_user_config(config_path) == {}


class TestDashboardHomeCoverage:
    def test_build_snapshot_returns_empty_when_loaders_fail(self, monkeypatch):
        monkeypatch.setattr(home_routes, "_load_apps", lambda: (_ for _ in ()).throw(RuntimeError("boom")))

        assert home_routes._build_snapshot() == {"has_data": False}

    def test_build_snapshot_prioritizes_overdue_drafted_and_review_items(self, monkeypatch):
        apps = [
            {"company": "Acme", "role": "Backend Engineer", "last_updated": "stale"},
            {"company": "Waiting Co", "role": "Platform Engineer", "last_updated": "fresh"},
            {"company": "Closed Co", "role": "Old Role", "last_updated": "closed"},
        ]
        queue_jobs = [{"company": "Queue Co", "role": "SWE", "status": "evaluated"}]
        people = [{"name": "Dana", "outreach_status": "drafted"}]
        health = [{"date": "health-old"}]
        age_map = {"stale": 21, "fresh": 2, "closed": 30, "health-old": 4}

        monkeypatch.setattr(home_routes, "_load_apps", lambda: apps)
        monkeypatch.setattr(home_routes, "_load_queue", lambda: queue_jobs)
        monkeypatch.setattr(home_routes, "_load_people", lambda: people)
        monkeypatch.setattr(home_routes, "_load_health", lambda: health)
        monkeypatch.setattr(home_routes, "_is_closed", lambda app: app["company"] == "Closed Co")
        monkeypatch.setattr(home_routes, "_is_waiting", lambda app: app["company"] == "Waiting Co")
        monkeypatch.setattr(home_routes, "_days_since", lambda value: age_map[value])
        monkeypatch.setattr(
            home_routes,
            "_check_overdue_followups",
            lambda active: ["[follow-up] Acme — Backend Engineer"],
        )

        snapshot = home_routes._build_snapshot()

        assert snapshot == {
            "has_data": True,
            "active": 2,
            "in_flight": 1,
            "closed": 1,
            "overdue": 1,
            "drafted_unsent": 1,
            "undecided": 1,
            "priorities": [
                "Follow up with Acme",
                "Send message to Dana",
                "Review: Acme — Backend Engineer",
            ],
        }

    def test_build_snapshot_uses_fallback_priorities_for_waiting_app(self, monkeypatch):
        apps = [{"company": "Waiting Co", "role": "Platform Engineer", "last_updated": "fresh"}]
        age_map = {"fresh": 1, "health-old": 5}

        monkeypatch.setattr(home_routes, "_load_apps", lambda: apps)
        monkeypatch.setattr(home_routes, "_load_queue", lambda: [])
        monkeypatch.setattr(home_routes, "_load_people", lambda: [])
        monkeypatch.setattr(home_routes, "_load_health", lambda: [{"date": "health-old"}])
        monkeypatch.setattr(home_routes, "_is_closed", lambda app: False)
        monkeypatch.setattr(home_routes, "_is_waiting", lambda app: True)
        monkeypatch.setattr(home_routes, "_days_since", lambda value: age_map[value])
        monkeypatch.setattr(home_routes, "_check_overdue_followups", lambda active: [])

        snapshot = home_routes._build_snapshot()

        assert snapshot["priorities"] == [
            "Check in on Waiting Co",
            "Apply to 2–3 new roles today",
            "Log a check-in after your session",
        ]

    def test_dashboard_home_renders_snapshot_cards(self, http_client_noauth, monkeypatch):
        monkeypatch.setattr(
            home_routes,
            "_build_snapshot",
            lambda: {
                "has_data": True,
                "active": 7,
                "in_flight": 3,
                "closed": 2,
                "overdue": 1,
                "drafted_unsent": 0,
                "undecided": 2,
                "priorities": [
                    "Follow up with Acme",
                    "Review: Beta Corp — Platform Engineer",
                    "Apply to 2–3 new roles today",
                ],
            },
        )

        response = http_client_noauth.get("/dashboard/")

        assert response.status_code == 200
        assert "Welcome back" in response.text
        # Hero pipeline panel: big-number counts
        assert "7</span>" in response.text          # active count
        assert "Pipeline &middot; Today" in response.text
        # Overdue badge (hero uses an SVG dot, not the old &#9888; glyph)
        assert "1 overdue" in response.text
        # Priority actions list driven by the snapshot
        assert "Priority Actions" in response.text
        assert "Review: Beta Corp" in response.text
        assert "Interviews" in response.text


class TestDashboardHomeApiCoverage:
    """GET /api/dashboard/home — JSON feed for the React SPA."""

    _SNAP = {
        "has_data": True,
        "active": 7,
        "in_flight": 3,
        "closed": 2,
        "overdue": 1,
        "drafted_unsent": 0,
        "undecided": 2,
        "priorities": [
            "Follow up with Acme",
            "Review: Beta Corp — Platform Engineer",
            "Apply to 2–3 new roles today",
        ],
    }

    def test_api_home_with_oura(self, http_client_noauth, monkeypatch):
        monkeypatch.setattr(dashboard_api_routes, "_build_snapshot", lambda: dict(self._SNAP))
        # Readiness only surfaces for a genuinely connected ring.
        monkeypatch.setattr(dashboard_api_routes, "_oura_status", lambda: {"connected": True})
        monkeypatch.setattr(
            dashboard_api_routes,
            "_load_oura",
            lambda: {
                "readiness_score": 82,
                "sleep_score": 88,
                "hrv": 64,
                "recovery_index": 91,
            },
        )

        response = http_client_noauth.get("/api/dashboard/home")
        assert response.status_code == 200
        body = response.json()

        # Top-level shape the React Home screen consumes.
        assert set(body) >= {"welcomeName", "hasOura", "oura", "today", "digest"}
        assert body["hasOura"] is True

        # Oura block shaped into score + label + three metric bars.
        oura = body["oura"]
        assert oura["score"] == 82
        assert oura["label"]  # non-empty readiness label
        assert [b["label"] for b in oura["bars"]] == ["Sleep score", "HRV", "Recovery index"]
        assert oura["bars"][2]["tone"] == "green"  # recovery uses the green tone
        assert oura["bars"][1]["unit"] == "ms"

        # Pipeline summary: snake_case in_flight is renamed to inflight.
        today = body["today"]
        assert today["active"] == 7
        assert today["inflight"] == 3
        assert today["overdue"] == 1
        assert "in_flight" not in today
        assert today["move"]  # today's move text rendered

        # String priorities are transformed into {n, text} objects.
        assert today["priorities"][0] == {"n": "1", "text": "Follow up with Acme"}
        assert today["priorities"][1]["n"] == "2"

    def test_api_home_without_oura_returns_null_block_and_digest(
        self, http_client_noauth, monkeypatch
    ):
        monkeypatch.setattr(dashboard_api_routes, "_build_snapshot", lambda: dict(self._SNAP))
        monkeypatch.setattr(dashboard_api_routes, "_oura_status", lambda: {"connected": False})
        monkeypatch.setattr(dashboard_api_routes, "_load_oura", lambda: None)

        response = http_client_noauth.get("/api/dashboard/home")
        assert response.status_code == 200
        body = response.json()

        assert body["hasOura"] is False
        assert body["oura"] is None

        # Digest fallback is always present so the no-ring state has content.
        digest = body["digest"]
        assert "date" in digest and digest["date"]
        labels = {item["label"] for item in digest["items"]}
        assert "Follow-ups due" in labels
        assert "New assessments ready" in labels

    def test_api_home_reading_without_connection_shows_digest(
        self, http_client_noauth, monkeypatch
    ):
        """A stale/zeroed readiness row must NOT flip Home into the readiness
        view when no ring is connected. Regression for the QA bug where Home
        defaulted to a zeroed-out Oura panel instead of the daily digest."""
        monkeypatch.setattr(dashboard_api_routes, "_build_snapshot", lambda: dict(self._SNAP))
        monkeypatch.setattr(dashboard_api_routes, "_oura_status", lambda: {"connected": False})
        monkeypatch.setattr(
            dashboard_api_routes,
            "_load_oura",
            lambda: {"readiness_score": 0, "sleep_score": 0, "hrv": 0, "recovery_index": 0},
        )

        response = http_client_noauth.get("/api/dashboard/home")
        assert response.status_code == 200
        body = response.json()

        # Disconnected -> no readiness, digest shown instead.
        assert body["hasOura"] is False
        assert body["oura"] is None
        assert body["digest"]["items"]

    def test_api_home_requires_auth(self, monkeypatch, isolated_server):
        """With auth enabled, an anonymous fetch is rejected (not a redirect)."""
        from fastapi.testclient import TestClient

        monkeypatch.setenv("API_KEY", "test-key")
        monkeypatch.delenv("ENABLE_REMOTE", raising=False)
        reset_settings_cache()
        with TestClient(create_app()) as client:
            response = client.get("/api/dashboard/home")
        reset_settings_cache()
        assert response.status_code in (401, 403)

    def test_api_me_returns_user_when_authed(self, http_client_noauth):
        response = http_client_noauth.get("/api/dashboard/me")
        assert response.status_code == 200
        body = response.json()
        assert body["authenticated"] is True
        assert "name" in body and "firstName" in body and "id" in body

    def test_api_me_requires_auth(self, monkeypatch, isolated_server):
        from fastapi.testclient import TestClient

        monkeypatch.setenv("API_KEY", "test-key")
        monkeypatch.delenv("ENABLE_REMOTE", raising=False)
        reset_settings_cache()
        with TestClient(create_app()) as client:
            response = client.get("/api/dashboard/me")
        reset_settings_cache()
        assert response.status_code in (401, 403)


class TestOuraAutoSyncOnHome:
    """Home load auto-refreshes Oura readiness (throttled + time-boxed).

    Covers _oura_sync_due / _auto_sync_oura and their wiring into
    GET /api/dashboard/home, so a connected ring populates without the user
    clicking "Sync now" in Settings.
    """

    @staticmethod
    def _naive_utc_now():
        return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)

    # ── _oura_sync_due: the throttle predicate ────────────────────────────────
    def test_sync_due_when_last_sync_empty(self):
        assert dashboard_api_routes._oura_sync_due("") is True

    def test_sync_due_when_last_sync_unparseable(self):
        assert dashboard_api_routes._oura_sync_due("not-a-timestamp") is True

    def test_sync_not_due_when_recent(self):
        recent = self._naive_utc_now().isoformat()
        assert dashboard_api_routes._oura_sync_due(recent) is False

    def test_sync_due_when_stale(self):
        stale = (self._naive_utc_now() - dt.timedelta(hours=2)).isoformat()
        assert dashboard_api_routes._oura_sync_due(stale) is True

    def test_sync_predicate_handles_tz_aware_timestamp(self):
        """A tz-aware last_sync is normalized to naive UTC before comparison."""
        fresh_aware = dt.datetime.now(dt.timezone.utc).isoformat()  # ends in +00:00
        stale_aware = (
            dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=2)
        ).isoformat()
        assert dashboard_api_routes._oura_sync_due(fresh_aware) is False
        assert dashboard_api_routes._oura_sync_due(stale_aware) is True

    # ── _auto_sync_oura: short-circuits + best-effort guarantees ───────────────
    def test_auto_sync_skips_when_not_connected(self, monkeypatch):
        calls = []
        monkeypatch.setattr("tools.oura.sync_oura", lambda: calls.append(1))
        asyncio.run(dashboard_api_routes._auto_sync_oura({"connected": False}))
        assert calls == []

    def test_auto_sync_skips_when_not_due(self, monkeypatch):
        calls = []
        monkeypatch.setattr("tools.oura.sync_oura", lambda: calls.append(1))
        recent = self._naive_utc_now().isoformat()
        asyncio.run(
            dashboard_api_routes._auto_sync_oura(
                {"connected": True, "last_sync": recent}
            )
        )
        assert calls == []

    def test_auto_sync_runs_when_connected_and_due(self, monkeypatch):
        calls = []
        monkeypatch.setattr("tools.oura.sync_oura", lambda: calls.append(1))
        asyncio.run(
            dashboard_api_routes._auto_sync_oura(
                {"connected": True, "last_sync": ""}
            )
        )
        assert calls == [1]

    def test_auto_sync_swallows_sync_errors(self, monkeypatch):
        def boom():
            raise RuntimeError("oura upstream down")

        monkeypatch.setattr("tools.oura.sync_oura", boom)
        # Must not raise — auto-sync is best-effort.
        asyncio.run(
            dashboard_api_routes._auto_sync_oura(
                {"connected": True, "last_sync": ""}
            )
        )

    def test_auto_sync_swallows_timeout(self, monkeypatch):
        import time

        monkeypatch.setattr(dashboard_api_routes, "_OURA_AUTOSYNC_TIMEOUT", 0.05)
        monkeypatch.setattr("tools.oura.sync_oura", lambda: time.sleep(0.3))
        # The wait_for cancels well before the sleep finishes; no exception escapes.
        asyncio.run(
            dashboard_api_routes._auto_sync_oura(
                {"connected": True, "last_sync": ""}
            )
        )

    # ── wiring: GET /api/dashboard/home triggers the auto-sync ─────────────────
    def _stub_home(self, monkeypatch, *, connected, last_sync):
        monkeypatch.setattr(
            dashboard_api_routes, "_build_snapshot", lambda: {"has_data": False}
        )
        monkeypatch.setattr(
            dashboard_api_routes,
            "_oura_status",
            lambda: {"connected": connected, "last_sync": last_sync},
        )
        monkeypatch.setattr(dashboard_api_routes, "_load_oura", lambda: None)

    def test_home_triggers_sync_when_stale(self, http_client_noauth, monkeypatch):
        calls = []
        monkeypatch.setattr("tools.oura.sync_oura", lambda: calls.append(1))
        self._stub_home(monkeypatch, connected=True, last_sync="")

        response = http_client_noauth.get("/api/dashboard/home")
        assert response.status_code == 200
        assert calls == [1]  # connected + stale -> one refresh

    def test_home_skips_sync_when_fresh(self, http_client_noauth, monkeypatch):
        calls = []
        monkeypatch.setattr("tools.oura.sync_oura", lambda: calls.append(1))
        recent = self._naive_utc_now().isoformat()
        self._stub_home(monkeypatch, connected=True, last_sync=recent)

        response = http_client_noauth.get("/api/dashboard/home")
        assert response.status_code == 200
        assert calls == []  # throttled -> no network

    def test_home_skips_sync_when_disconnected(self, http_client_noauth, monkeypatch):
        calls = []
        monkeypatch.setattr("tools.oura.sync_oura", lambda: calls.append(1))
        self._stub_home(monkeypatch, connected=False, last_sync="")

        response = http_client_noauth.get("/api/dashboard/home")
        assert response.status_code == 200
        assert calls == []  # no ring -> no sync attempt

    def test_home_survives_sync_failure(self, http_client_noauth, monkeypatch):
        def boom():
            raise RuntimeError("oura upstream down")

        monkeypatch.setattr("tools.oura.sync_oura", boom)
        self._stub_home(monkeypatch, connected=True, last_sync="")

        response = http_client_noauth.get("/api/dashboard/home")
        assert response.status_code == 200  # best-effort: failure never breaks Home


class TestDashboardApiKeysJsonCoverage:
    """GET/POST /api/dashboard/api-keys — JSON token management for the SPA.

    Distinct from TestDashboardApiKeysCoverage, which exercises the legacy
    server-rendered /dashboard/api-keys HTML page. These cover the JSON feed
    the React API Keys screen consumes.
    """

    def test_list_keys_returns_shaped_rows(self, http_client_noauth, monkeypatch):
        monkeypatch.setattr(
            dashboard_api_routes,
            "list_keys",
            lambda _oid: [
                SimpleNamespace(
                    id=3,
                    label="Phone Shortcut",
                    created_at="2026-06-28T20:00:00",
                    last_used_at="2026-06-29T08:30:00",
                ),
                SimpleNamespace(
                    id=4,
                    label="",
                    created_at="2026-06-27T10:00:00",
                    last_used_at=None,
                ),
            ],
        )

        response = http_client_noauth.get("/api/dashboard/api-keys")
        assert response.status_code == 200
        keys = response.json()["keys"]
        assert keys[0] == {
            "id": 3,
            "label": "Phone Shortcut",
            "created_at": "2026-06-28T20:00:00",
            "last_used_at": "2026-06-29T08:30:00",
        }
        # Unlabeled / never-used rows collapse None to empty strings.
        assert keys[1]["label"] == ""
        assert keys[1]["last_used_at"] == ""

    def test_create_key_returns_plaintext_once(self, http_client_noauth, monkeypatch):
        calls = {}
        monkeypatch.setattr(
            dashboard_api_routes,
            "create_key",
            lambda oid, label: calls.update({"args": (oid, label)})
            or (9, "jcmcp_brand_new_token"),
        )

        response = http_client_noauth.post(
            "/api/dashboard/api-keys",
            json={"label": "  CLI on Home Mac  "},
        )
        assert response.status_code == 201
        body = response.json()
        assert body == {
            "id": 9,
            "label": "CLI on Home Mac",
            "token": "jcmcp_brand_new_token",
        }
        # Label is trimmed and the key is scoped to the resolved admin OID.
        assert calls["args"] == ("admin", "CLI on Home Mac")

    def test_create_key_defaults_blank_label(self, http_client_noauth, monkeypatch):
        monkeypatch.setattr(
            dashboard_api_routes,
            "create_key",
            lambda _oid, _label: (1, "jcmcp_token"),
        )

        response = http_client_noauth.post("/api/dashboard/api-keys", json={})
        assert response.status_code == 201
        assert response.json()["label"] == ""

    def test_revoke_key_reports_success(self, http_client_noauth, monkeypatch):
        calls = {}
        monkeypatch.setattr(
            dashboard_api_routes,
            "revoke_key",
            lambda key_id, oid: calls.update({"args": (key_id, oid)}) or True,
        )

        response = http_client_noauth.post("/api/dashboard/api-keys/11/revoke")
        assert response.status_code == 200
        assert response.json() == {"revoked": True}
        assert calls["args"] == (11, "admin")

    def test_revoke_missing_key_reports_false(self, http_client_noauth, monkeypatch):
        monkeypatch.setattr(
            dashboard_api_routes, "revoke_key", lambda _key_id, _oid: False
        )

        response = http_client_noauth.post("/api/dashboard/api-keys/999/revoke")
        assert response.status_code == 200
        assert response.json() == {"revoked": False}

    def test_api_keys_require_auth(self, monkeypatch, isolated_server):
        from fastapi.testclient import TestClient

        monkeypatch.setenv("API_KEY", "test-key")
        monkeypatch.delenv("ENABLE_REMOTE", raising=False)
        reset_settings_cache()
        with TestClient(create_app()) as client:
            assert client.get("/api/dashboard/api-keys").status_code in (401, 403)
            assert client.post(
                "/api/dashboard/api-keys", json={"label": "x"}
            ).status_code in (401, 403)
            assert client.post(
                "/api/dashboard/api-keys/1/revoke"
            ).status_code in (401, 403)
        reset_settings_cache()


class TestDashboardSettingsApiCoverage:
    """GET /api/dashboard/settings: read-only status summary for the SPA."""

    def test_settings_summary_reports_status_flags(
        self, http_client_noauth, monkeypatch
    ):
        monkeypatch.setattr(dashboard_api_routes, "_is_owner", lambda: True)
        monkeypatch.setattr(dashboard_api_routes, "_openai_key_set", lambda: True)
        monkeypatch.setattr(
            dashboard_api_routes,
            "_oura_status",
            lambda: {
                "configured": True,
                "connected": True,
                "last_sync": "2026-06-29T08:00:00",
                "scope": "daily",
            },
        )
        monkeypatch.setattr(
            dashboard_api_routes, "_load_oura", lambda: {"readiness_score": 70}
        )
        monkeypatch.delenv("LLM_PROVIDER", raising=False)  # CI sets foundry

        response = http_client_noauth.get("/api/dashboard/settings")
        assert response.status_code == 200
        assert response.json() == {
            "isOwner": True,
            "openaiKeySet": True,
            "aiProvider": "openai",
            "ouraConfigured": True,
            "ouraConnected": True,
            "ouraViaSync": False,
            "ouraLastSync": "2026-06-29T08:00:00",
            "oura": {
                "date": "",
                "readiness_score": 70,
                "sleep_score": 0,
                "hrv": 0,
                "recovery_index": 0,
            },
            "classicUrl": "/dashboard/settings",
        }

    def test_settings_summary_defaults_when_unconfigured(
        self, http_client_noauth, monkeypatch
    ):
        monkeypatch.setattr(dashboard_api_routes, "_is_owner", lambda: False)
        monkeypatch.setattr(dashboard_api_routes, "_openai_key_set", lambda: False)
        monkeypatch.setattr(
            dashboard_api_routes,
            "_oura_status",
            lambda: {"configured": False, "connected": False, "last_sync": "", "scope": ""},
        )
        monkeypatch.setattr(dashboard_api_routes, "_load_oura", lambda: None)

        response = http_client_noauth.get("/api/dashboard/settings")
        assert response.status_code == 200
        body = response.json()
        assert body["isOwner"] is False
        assert body["openaiKeySet"] is False
        assert body["ouraConfigured"] is False
        assert body["ouraConnected"] is False
        assert body["ouraLastSync"] == ""
        assert body["oura"] is None
        assert body["classicUrl"] == "/dashboard/settings"

    def test_settings_requires_auth(self, monkeypatch, isolated_server):
        from fastapi.testclient import TestClient

        monkeypatch.setenv("API_KEY", "test-key")
        monkeypatch.delenv("ENABLE_REMOTE", raising=False)
        reset_settings_cache()
        with TestClient(create_app()) as client:
            response = client.get("/api/dashboard/settings")
        reset_settings_cache()
        assert response.status_code in (401, 403)


class TestOpenAiKeySetHelper:
    """_openai_key_set() must be tenant-aware (PR #67 Copilot review, #1).

    It mirrors lib.config.get_llm_client()'s resolution so the Settings screen
    reports the same truth generation sees: the LLM_API_KEY env var OR the
    active tenant's merged config openai_api_key. This must work for
    single-tenant/local and owner sessions, not only when a per-user
    data-folder override is active.
    """

    def test_true_from_active_config(self, monkeypatch):
        import lib.config as config

        monkeypatch.delenv("LLM_API_KEY", raising=False)
        monkeypatch.delenv("LLM_PROVIDER", raising=False)  # CI sets foundry
        monkeypatch.setattr(config, "get_active_config", lambda: {"openai_api_key": "sk-abc"})
        assert dashboard_api_routes._openai_key_set() is True

    def test_true_from_env_even_without_config_key(self, monkeypatch):
        import lib.config as config

        monkeypatch.setenv("LLM_API_KEY", "env-provided-key")
        monkeypatch.delenv("LLM_PROVIDER", raising=False)  # CI sets foundry
        monkeypatch.setattr(config, "get_active_config", lambda: {})
        assert dashboard_api_routes._openai_key_set() is True

    def test_false_when_no_key_anywhere(self, monkeypatch):
        import lib.config as config

        monkeypatch.delenv("LLM_API_KEY", raising=False)
        monkeypatch.delenv("LLM_PROVIDER", raising=False)  # CI sets foundry
        monkeypatch.setattr(config, "get_active_config", lambda: {"openai_api_key": "   "})
        assert dashboard_api_routes._openai_key_set() is False

    def test_provider_branches(self, monkeypatch):
        """llm_generation_status must report each provider's own readiness:
        anthropic by anthropic_api_key, ollama always (local endpoint),
        foundry by endpoint (key may come from workload identity)."""
        import lib.config as config

        monkeypatch.delenv("LLM_API_KEY", raising=False)
        monkeypatch.delenv("LLM_PROVIDER", raising=False)

        cases = [
            ({"llm_provider": "anthropic", "anthropic_api_key": "sk-ant"}, ("anthropic", True)),
            ({"llm_provider": "anthropic", "openai_api_key": "sk-abc"}, ("anthropic", False)),
            ({"llm_provider": "ollama"}, ("ollama", True)),
            ({"llm_provider": "foundry", "azure_foundry_endpoint": "https://x.ai"}, ("foundry", True)),
            ({"llm_provider": "foundry"}, ("foundry", False)),
        ]
        for cfg, expected in cases:
            monkeypatch.setattr(config, "get_active_config", lambda c=cfg: c)
            assert config.llm_generation_status() == expected, cfg

    def test_env_provider_overrides_config(self, monkeypatch):
        import lib.config as config

        monkeypatch.delenv("LLM_API_KEY", raising=False)
        monkeypatch.setenv("LLM_PROVIDER", "anthropic")
        monkeypatch.setattr(
            config, "get_active_config",
            lambda: {"llm_provider": "openai", "anthropic_api_key": "sk-ant"},
        )
        assert config.llm_generation_status() == ("anthropic", True)

    def test_false_and_safe_on_config_error(self, monkeypatch):
        import lib.config as config

        monkeypatch.delenv("LLM_API_KEY", raising=False)

        def boom():
            raise RuntimeError("no request context")

        monkeypatch.setattr(config, "get_active_config", boom)
        assert dashboard_api_routes._openai_key_set() is False


class TestHomeHeroBuilders:
    """Direct coverage for home.py hero HTML builders + readiness band helpers."""

    def test_readiness_color_and_label_bands(self):
        from transport.http.routes.dashboard import home

        assert home._readiness_color_and_label(90) == ("#22C55E", "High readiness")
        assert home._readiness_color_and_label(72) == ("#f59e0b", "Good readiness")
        assert home._readiness_color_and_label(40) == ("#ef4444", "Low readiness")

    def test_metric_bar_color_bands(self):
        from transport.http.routes.dashboard import home

        assert home._metric_bar_color(80) == "#22C55E"
        assert home._metric_bar_color(60) == "#f59e0b"
        assert home._metric_bar_color(10) == "#ef4444"

    def test_today_move_text_readiness_variants(self):
        from transport.http.routes.dashboard import home

        assert "High readiness" in home._today_move_text({"readiness_score": 90}, {"overdue": 0})
        assert "Decent readiness" in home._today_move_text({"readiness_score": 74}, {})
        low = home._today_move_text({"readiness_score": 40}, {"overdue": 2})
        assert "Recovery day" in low
        assert "2 overdue task" in low

    def test_today_move_text_no_oura_paths(self):
        from transport.http.routes.dashboard import home

        assert "in flight" in home._today_move_text(None, {"in_flight": 3})
        assert "top priority" in home._today_move_text(None, {"in_flight": 0, "overdue": 0})

    def test_build_hero_html_with_oura_and_data(self):
        from transport.http.routes.dashboard import home

        snap = {
            "has_data": True, "active": 2, "in_flight": 1, "overdue": 1,
            "priorities": ["Follow up with Acme"],
        }
        oura = {"readiness_score": 88, "sleep_score": 80, "hrv": 65, "recovery_index": 90}
        out = home._build_hero_html("Frank", snap, oura)
        assert "oura-panel" in out
        assert ">88<" in out
        assert "High readiness" in out
        assert "1 overdue" in out
        assert "Follow up with Acme" in out
        assert "Active" in out

    def test_build_hero_html_without_oura_no_data(self):
        from transport.http.routes.dashboard import home

        snap = {"has_data": False, "active": 0, "in_flight": 0, "overdue": 0, "priorities": []}
        out = home._build_hero_html("there", snap, None)
        assert "oura-panel" not in out
        assert "What would you like to work on today?" in out


class TestOuraBrowserOAuthRoutes:
    """Browser OAuth connect/callback handlers in dashboard/oura.py."""

    def test_connect_unavailable_when_not_configured(self, http_client_noauth, monkeypatch):
        from transport.http.routes.dashboard import oura as oura_route

        monkeypatch.setattr(oura_route.oura, "oura_configured", lambda: False)
        r = http_client_noauth.get("/dashboard/oura/connect", follow_redirects=False)
        assert r.status_code == 303
        assert "oura=unavailable" in r.headers["location"]

    def test_connect_redirects_to_oura_with_state_cookie(self, http_client_noauth, monkeypatch):
        from transport.http.routes.dashboard import oura as oura_route

        monkeypatch.setattr(oura_route.oura, "oura_configured", lambda: True)
        monkeypatch.setattr(
            oura_route.oura, "oura_authorize_url",
            lambda state, redirect_uri: f"https://cloud.ouraring.com/oauth/authorize?state={state}",
        )
        r = http_client_noauth.get("/dashboard/oura/connect", follow_redirects=False)
        assert r.status_code == 302
        assert r.headers["location"].startswith("https://cloud.ouraring.com/oauth/authorize")
        assert "oura_state=" in r.headers.get("set-cookie", "")

    def test_callback_error_param_redirects_error(self, http_client_noauth):
        r = http_client_noauth.get(
            "/dashboard/oura/callback?error=access_denied", follow_redirects=False
        )
        assert r.status_code == 303
        assert "oura=error" in r.headers["location"]

    def test_callback_missing_code_redirects_error(self, http_client_noauth):
        r = http_client_noauth.get("/dashboard/oura/callback", follow_redirects=False)
        assert r.status_code == 303
        assert "oura=error" in r.headers["location"]

    def test_callback_state_mismatch_redirects_error(self, http_client_noauth):
        # No state cookie set → expected is empty → mismatch → error.
        r = http_client_noauth.get(
            "/dashboard/oura/callback?code=abc&state=xyz", follow_redirects=False
        )
        assert r.status_code == 303
        assert "oura=error" in r.headers["location"]

    def test_callback_success_flow(self, http_client_noauth, monkeypatch):
        from transport.http.routes.dashboard import oura as oura_route

        monkeypatch.setattr(
            oura_route.oura, "exchange_code_for_tokens",
            lambda code, redirect_uri: {"access_token": "a", "refresh_token": "r"},
        )
        monkeypatch.setattr(oura_route.oura, "save_oura_tokens", lambda tokens: None)
        monkeypatch.setattr(oura_route.oura, "sync_oura", lambda: {"ok": True})
        http_client_noauth.cookies.set("oura_state", "match-state")
        r = http_client_noauth.get(
            "/dashboard/oura/callback?code=abc&state=match-state", follow_redirects=False
        )
        assert r.status_code == 303
        assert "oura=connected" in r.headers["location"]

    def test_callback_success_tolerates_sync_failure(self, http_client_noauth, monkeypatch):
        from transport.http.routes.dashboard import oura as oura_route

        monkeypatch.setattr(
            oura_route.oura, "exchange_code_for_tokens",
            lambda code, redirect_uri: {"access_token": "a", "refresh_token": "r"},
        )
        monkeypatch.setattr(oura_route.oura, "save_oura_tokens", lambda tokens: None)

        def sync_boom():
            raise RuntimeError("sync hiccup")

        monkeypatch.setattr(oura_route.oura, "sync_oura", sync_boom)
        http_client_noauth.cookies.set("oura_state", "match-state")
        r = http_client_noauth.get(
            "/dashboard/oura/callback?code=abc&state=match-state", follow_redirects=False
        )
        # Connect must still succeed even if the best-effort first sync fails.
        assert r.status_code == 303
        assert "oura=connected" in r.headers["location"]

    def test_callback_exchange_error_redirects_error(self, http_client_noauth, monkeypatch):
        from transport.http.routes.dashboard import oura as oura_route

        def boom(code, redirect_uri):
            raise oura_route.oura.OuraError("bad code")

        monkeypatch.setattr(oura_route.oura, "exchange_code_for_tokens", boom)
        http_client_noauth.cookies.set("oura_state", "match-state")
        r = http_client_noauth.get(
            "/dashboard/oura/callback?code=abc&state=match-state", follow_redirects=False
        )
        assert r.status_code == 303
        assert "oura=error" in r.headers["location"]


class TestDashboardOuraApiCoverage:
    """POST /api/dashboard/oura/sync + /disconnect: OAuth-backed Oura actions.

    The browser connect/callback handshake is covered separately; these cover
    the JSON actions the React Settings screen calls once a ring is connected.
    """

    def test_oura_sync_pulls_and_returns_latest(self, http_client_noauth, monkeypatch):
        import tools.oura as oura_tool

        monkeypatch.setattr(
            oura_tool,
            "sync_oura",
            lambda: {"ok": True, "connected": True, "reading": {"readiness_score": 88}},
        )
        monkeypatch.setattr(
            dashboard_api_routes,
            "_oura_status",
            lambda: {"configured": True, "connected": True, "last_sync": "x", "scope": "daily"},
        )
        monkeypatch.setattr(
            dashboard_api_routes,
            "_load_oura",
            lambda: {
                "date": "2026-06-29",
                "readiness_score": 88,
                "sleep_score": 90,
                "hrv": 65,
                "recovery_index": 80,
            },
        )

        response = http_client_noauth.post("/api/dashboard/oura/sync", json={})
        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert body["ouraConnected"] is True
        assert body["oura"]["readiness_score"] == 88

    def test_oura_sync_no_data_still_ok(self, http_client_noauth, monkeypatch):
        import tools.oura as oura_tool

        monkeypatch.setattr(
            oura_tool,
            "sync_oura",
            lambda: {"ok": True, "connected": True, "reading": None, "note": "no_data"},
        )
        monkeypatch.setattr(
            dashboard_api_routes,
            "_oura_status",
            lambda: {"configured": True, "connected": True, "last_sync": "x", "scope": "daily"},
        )
        monkeypatch.setattr(dashboard_api_routes, "_load_oura", lambda: None)

        response = http_client_noauth.post("/api/dashboard/oura/sync", json={})
        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert body["note"] == "no_data"
        assert body["oura"] is None

    def test_oura_sync_not_connected_returns_409(self, http_client_noauth, monkeypatch):
        import tools.oura as oura_tool

        monkeypatch.setattr(
            oura_tool,
            "sync_oura",
            lambda: {"ok": False, "connected": False, "error": "not_connected"},
        )
        monkeypatch.setattr(
            dashboard_api_routes,
            "_oura_status",
            lambda: {"configured": True, "connected": False, "last_sync": "", "scope": ""},
        )
        monkeypatch.setattr(dashboard_api_routes, "_load_oura", lambda: None)

        response = http_client_noauth.post("/api/dashboard/oura/sync", json={})
        assert response.status_code == 409
        assert response.json()["error"] == "not_connected"

    def test_oura_sync_upstream_error_returns_502(self, http_client_noauth, monkeypatch):
        import tools.oura as oura_tool

        monkeypatch.setattr(
            oura_tool,
            "sync_oura",
            lambda: {"ok": False, "connected": True, "error": "Oura API daily_readiness returned 500"},
        )
        monkeypatch.setattr(
            dashboard_api_routes,
            "_oura_status",
            lambda: {"configured": True, "connected": True, "last_sync": "", "scope": "daily"},
        )
        monkeypatch.setattr(dashboard_api_routes, "_load_oura", lambda: None)

        response = http_client_noauth.post("/api/dashboard/oura/sync", json={})
        assert response.status_code == 502
        assert response.json()["ok"] is False

    def test_oura_disconnect_clears_tokens(self, http_client_noauth, monkeypatch):
        import tools.oura as oura_tool

        captured = {}

        def _clear():
            captured["called"] = True
            return True

        monkeypatch.setattr(oura_tool, "clear_oura_tokens", _clear)

        response = http_client_noauth.post("/api/dashboard/oura/disconnect", json={})
        assert response.status_code == 200
        assert response.json() == {"ok": True, "removed": True, "ouraConnected": False}
        assert captured["called"] is True

    def test_oura_sync_requires_auth(self, monkeypatch, isolated_server):
        from fastapi.testclient import TestClient

        monkeypatch.setenv("API_KEY", "test-key")
        monkeypatch.delenv("ENABLE_REMOTE", raising=False)
        reset_settings_cache()
        with TestClient(create_app()) as client:
            response = client.post("/api/dashboard/oura/sync", json={})
        reset_settings_cache()
        assert response.status_code in (401, 403)

    def test_oura_disconnect_requires_auth(self, monkeypatch, isolated_server):
        from fastapi.testclient import TestClient

        monkeypatch.setenv("API_KEY", "test-key")
        monkeypatch.delenv("ENABLE_REMOTE", raising=False)
        reset_settings_cache()
        with TestClient(create_app()) as client:
            response = client.post("/api/dashboard/oura/disconnect", json={})
        reset_settings_cache()
        assert response.status_code in (401, 403)


class TestDashboardOuraConnectRoute:
    """GET /dashboard/oura/connect: the browser OAuth handshake entry point.

    Regression guard: this router must stay mounted. A prior wiring gap left it
    out of the dashboard package __init__, making connect/callback 404.
    """

    def test_connect_unconfigured_redirects_to_settings(
        self, http_client_noauth, monkeypatch
    ):
        import tools.oura as oura_tool

        monkeypatch.setattr(oura_tool, "oura_configured", lambda: False)
        response = http_client_noauth.get(
            "/dashboard/oura/connect", follow_redirects=False
        )
        assert response.status_code == 303
        assert response.headers["location"] == "/app/settings?oura=unavailable"

    def test_connect_configured_redirects_to_oura(
        self, http_client_noauth, monkeypatch
    ):
        import tools.oura as oura_tool

        monkeypatch.setattr(oura_tool, "oura_configured", lambda: True)
        monkeypatch.setattr(
            oura_tool,
            "oura_authorize_url",
            lambda state, redirect_uri: f"https://cloud.ouraring.com/oauth/authorize?state={state}",
        )
        response = http_client_noauth.get(
            "/dashboard/oura/connect", follow_redirects=False
        )
        assert response.status_code == 302
        assert response.headers["location"].startswith(
            "https://cloud.ouraring.com/oauth/authorize?state="
        )
        # A state cookie is set so the callback can verify the handshake.
        assert "oura_state" in response.headers.get("set-cookie", "")


class TestSafeNextRedirect:
    """_safe_next gates post-login redirects to internal SPA/dashboard paths."""

    @pytest.mark.parametrize(
        "candidate,expected",
        [
            ("/app", "/app"),
            ("/app/job-hunt", "/app/job-hunt"),
            ("/dashboard", "/dashboard"),
            ("/dashboard/people", "/dashboard/people"),
            # Anything off-allowlist or unsafe falls back to the SPA root.
            ("/api/dashboard/home", "/app"),
            ("https://evil.example/app", "/app"),
            ("//evil.example", "/app"),
            ("", "/app"),
            (None, "/app"),
        ],
    )
    def test_safe_next(self, candidate, expected):
        assert login_routes._safe_next(candidate) == expected


class TestSpaServing:
    """/app/* — Vite-built React SPA served by FastAPI."""

    @staticmethod
    def _make_dist(tmp_path):
        dist = tmp_path / "dist"
        (dist / "assets").mkdir(parents=True)
        (dist / "index.html").write_text('<!doctype html><html><body><div id="root"></div></body></html>')
        (dist / "assets" / "app.js").write_text('console.log("spa")')
        return dist

    @pytest.fixture()
    def spa_client(self, tmp_path, monkeypatch, isolated_server):
        from fastapi.testclient import TestClient
        import transport.http.app as app_module

        monkeypatch.setattr(app_module, "_SPA_DIST", self._make_dist(tmp_path))
        monkeypatch.delenv("API_KEY", raising=False)
        monkeypatch.delenv("ENABLE_REMOTE", raising=False)
        reset_settings_cache()
        with TestClient(app_module.create_app()) as client:
            yield client
        reset_settings_cache()

    def test_app_shell_served(self, spa_client):
        response = spa_client.get("/app")
        assert response.status_code == 200
        assert '<div id="root">' in response.text

    def test_deep_link_falls_back_to_index(self, spa_client):
        # No file on disk for this client-side route → SPA fallback to index.
        response = spa_client.get("/app/job-hunt")
        assert response.status_code == 200
        assert '<div id="root">' in response.text

    def test_hashed_asset_is_served(self, spa_client):
        response = spa_client.get("/app/assets/app.js")
        assert response.status_code == 200
        assert "spa" in response.text

    def test_shell_public_but_data_api_protected_under_auth(
        self, tmp_path, monkeypatch, isolated_server
    ):
        from fastapi.testclient import TestClient
        import transport.http.app as app_module

        monkeypatch.setattr(app_module, "_SPA_DIST", self._make_dist(tmp_path))
        monkeypatch.setenv("API_KEY", "test-key")
        monkeypatch.delenv("ENABLE_REMOTE", raising=False)
        reset_settings_cache()
        with TestClient(app_module.create_app()) as client:
            # Static shell loads without credentials so the SPA can boot.
            assert client.get("/app").status_code == 200
            # User data stays behind auth.
            assert client.get("/api/dashboard/home").status_code in (401, 403)
        reset_settings_cache()

    def test_mount_skipped_when_dist_absent(self, tmp_path, monkeypatch, isolated_server):
        from fastapi.testclient import TestClient
        import transport.http.app as app_module

        monkeypatch.setattr(app_module, "_SPA_DIST", tmp_path / "does-not-exist")
        monkeypatch.delenv("API_KEY", raising=False)
        monkeypatch.delenv("ENABLE_REMOTE", raising=False)
        reset_settings_cache()
        with TestClient(app_module.create_app()) as client:
            # No SPA mount → the shell is never served.
            response = client.get("/app")
            assert '<div id="root">' not in response.text
        reset_settings_cache()


class TestDashboardInterviewsCoverage:
    def test_interviews_payload_sorts_upcoming_and_recent(self, monkeypatch):
        today = dt.date.today()
        monkeypatch.setattr(
            interviews_routes,
            "_load_json",
            lambda *_args, **_kwargs: {
                "interviews": [
                    {
                        "company": "Future Co",
                        "role": "Staff Engineer",
                        "interview_date": (today + dt.timedelta(days=4)).isoformat(),
                    },
                    {
                        "company": "Past Co",
                        "role": "Backend Engineer",
                        "interview_date": (today - dt.timedelta(days=2)).isoformat(),
                    },
                    {
                        "company": "Today Co",
                        "role": "Platform Engineer",
                        "interview_date": today.isoformat(),
                    },
                    {
                        "company": "Unknown Co",
                        "role": "Mystery",
                        "interview_date": "not-a-date",
                    },
                ]
            },
        )

        payload = interviews_routes._interviews_payload()

        assert payload["total"] == 4
        assert [item["company"] for item in payload["upcoming"]] == ["Today Co", "Future Co"]
        assert [item["company"] for item in payload["recent"]] == ["Unknown Co", "Past Co"]

    def test_interviews_data_endpoint_returns_sorted_payload(self, http_client_noauth, monkeypatch):
        today = dt.date.today()
        monkeypatch.setattr(
            interviews_routes,
            "_load_json",
            lambda *_args, **_kwargs: {
                "interviews": [
                    {
                        "company": "Future Co",
                        "role": "Staff Engineer",
                        "interview_date": (today + dt.timedelta(days=1)).isoformat(),
                    },
                    {
                        "company": "Past Co",
                        "role": "Backend Engineer",
                        "interview_date": (today - dt.timedelta(days=1)).isoformat(),
                    },
                ]
            },
        )

        response = http_client_noauth.get("/dashboard/interviews/data")

        assert response.status_code == 200
        assert response.json()["upcoming"][0]["company"] == "Future Co"
        assert response.json()["recent"][0]["company"] == "Past Co"

    def test_interviews_board_renders_html(self, http_client_noauth):
        response = http_client_noauth.get("/dashboard/interviews")

        assert response.status_code == 200
        assert "Upcoming Interviews" in response.text
        assert "Recent Debriefs" in response.text
        assert "boot()" in response.text

    def _payload_with(self, monkeypatch, interviews):
        monkeypatch.setattr(
            interviews_routes,
            "_load_json",
            lambda *_args, **_kwargs: {"interviews": interviews},
        )
        return interviews_routes._interviews_payload()

    def test_today_with_debrief_lands_in_debriefs_not_upcoming(self, monkeypatch):
        """A debrief dated today leaves Upcoming the moment it has content."""
        today = dt.date.today()
        payload = self._payload_with(
            monkeypatch,
            [{"company": "Debriefed Co", "interview_date": today.isoformat(), "self_rating": 8}],
        )

        assert [iv["company"] for iv in payload["upcoming"]] == []
        assert [iv["company"] for iv in payload["recent"]] == ["Debriefed Co"]

    def test_today_without_debrief_lands_in_upcoming_not_debriefs(self, monkeypatch):
        today = dt.date.today()
        payload = self._payload_with(
            monkeypatch,
            [{"company": "Scheduled Co", "interview_date": today.isoformat()}],
        )

        assert [iv["company"] for iv in payload["upcoming"]] == ["Scheduled Co"]
        assert [iv["company"] for iv in payload["recent"]] == []

    def test_future_without_debrief_is_upcoming(self, monkeypatch):
        today = dt.date.today()
        payload = self._payload_with(
            monkeypatch,
            [{"company": "Future Co", "interview_date": (today + dt.timedelta(days=3)).isoformat()}],
        )

        assert [iv["company"] for iv in payload["upcoming"]] == ["Future Co"]
        assert [iv["company"] for iv in payload["recent"]] == []

    def test_debrief_detected_from_any_populated_field(self, monkeypatch):
        """what_landed / what_didnt / verbatim_quotes each mark a debrief even
        when the interview is dated in the future."""
        today = dt.date.today()
        future = (today + dt.timedelta(days=2)).isoformat()
        payload = self._payload_with(
            monkeypatch,
            [
                {"company": "Landed Co", "interview_date": future, "what_landed": ["strong system design"]},
                {"company": "Didnt Co", "interview_date": future, "what_didnt": ["rambled on scaling"]},
                {"company": "Quotes Co", "interview_date": future, "verbatim_quotes": ["we'd move fast"]},
                {"company": "Empty Co", "interview_date": future, "what_landed": []},
            ],
        )

        assert set(iv["company"] for iv in payload["upcoming"]) == {"Empty Co"}
        assert set(iv["company"] for iv in payload["recent"]) == {"Landed Co", "Didnt Co", "Quotes Co"}


class TestDashboardApiKeysCoverage:
    def test_key_row_html_handles_used_and_unlabeled_keys(self):
        used_row = api_keys_routes._key_row_html(
            7,
            "Phone <Shortcut>",
            "2026-06-28T20:00:00",
            "2026-06-29T08:30:00",
        )
        unlabeled_row = api_keys_routes._key_row_html(
            8,
            "",
            "2026-06-28T20:00:00",
            None,
        )

        assert "Phone &lt;Shortcut&gt;" in used_row
        assert "2026-06-29" in used_row
        assert "/dashboard/api-keys/7/revoke" in used_row
        assert "unlabeled" in unlabeled_row
        assert "Never" in unlabeled_row

    def test_api_keys_page_renders_empty_state(self, http_client_authed, monkeypatch):
        monkeypatch.setattr(api_keys_routes, "list_keys", lambda _oid: [])

        response = http_client_authed.get(
            "/dashboard/api-keys",
            headers={"Authorization": "Bearer test-key"},
        )

        assert response.status_code == 200
        assert "No API keys yet" in response.text
        assert "Generate a new API key" in response.text

    def test_generate_and_revoke_api_key_routes(self, http_client_authed, monkeypatch):
        calls = {"create": None, "revoke": None}

        monkeypatch.setattr(
            api_keys_routes,
            "list_keys",
            lambda _oid: [
                SimpleNamespace(
                    id=11,
                    label="CLI Key",
                    created_at="2026-06-28T20:00:00",
                    last_used_at="2026-06-28T21:00:00",
                )
            ],
        )
        monkeypatch.setattr(
            api_keys_routes,
            "create_key",
            lambda oid, label: calls.update({"create": (oid, label)}) or (11, "jcmcp_new_secret"),
        )
        monkeypatch.setattr(
            api_keys_routes,
            "revoke_key",
            lambda key_id, oid: calls.update({"revoke": (key_id, oid)}),
        )

        generate_response = http_client_authed.post(
            "/dashboard/api-keys",
            headers={"Authorization": "Bearer test-key"},
            data={"label": "  Home Mac CLI  "},
        )
        revoke_response = http_client_authed.post(
            "/dashboard/api-keys/11/revoke",
            headers={"Authorization": "Bearer test-key"},
            follow_redirects=False,
        )

        assert generate_response.status_code == 200
        assert "New API key generated" in generate_response.text
        assert "jcmcp_new_secret" in generate_response.text
        assert "CLI Key" in generate_response.text
        assert calls["create"] == ("admin", "Home Mac CLI")
        assert revoke_response.status_code == 303
        assert revoke_response.headers["location"] == "/dashboard/api-keys"
        assert calls["revoke"] == (11, "admin")


class TestDashboardDigestCoverage:
    def test_digest_generate_returns_tool_output(self, http_client_noauth, monkeypatch):
        monkeypatch.setattr(digest_routes, "get_daily_digest", lambda: "Digest body")

        response = http_client_noauth.post("/dashboard/digest/generate")

        assert response.status_code == 200
        assert response.json() == {"digest": "Digest body"}

    def test_digest_page_renders_generate_ui(self, http_client_noauth):
        response = http_client_noauth.get("/dashboard/digest")

        assert response.status_code == 200
        assert "Generate Today's Digest" in response.text
        assert "No digest generated yet." in response.text
        assert "WAITING ON OTHERS" in response.text


class TestDashboardAssetsCoverage:
    def test_logo_and_banner_svg_return_empty_on_read_error(self, monkeypatch):
        def _raise_oserror(*_args, **_kwargs):
            raise OSError("missing")

        monkeypatch.setattr(
            assets_routes,
            "_LOGO_SVG_PATH",
            SimpleNamespace(read_text=_raise_oserror),
        )
        monkeypatch.setattr(
            assets_routes,
            "_BANNER_SVG_PATH",
            SimpleNamespace(read_text=_raise_oserror),
        )

        assert assets_routes.logo_svg() == ""
        assert assets_routes.banner_svg() == ""

    def test_logo_endpoint_serves_svg_file(self, http_client_noauth, isolated_server, monkeypatch):
        logo_path = isolated_server / "logo.svg"
        logo_path.write_text("<svg>ok</svg>", encoding="utf-8")
        monkeypatch.setattr(assets_routes, "_LOGO_SVG_PATH", logo_path)

        response = http_client_noauth.get("/dashboard/logo")

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("image/svg+xml")
        assert "<svg>ok</svg>" in response.text

    def test_logo_endpoint_returns_not_found_when_svg_missing(self, http_client_noauth, isolated_server, monkeypatch):
        monkeypatch.setattr(assets_routes, "_LOGO_SVG_PATH", isolated_server / "missing-logo.svg")

        response = http_client_noauth.get("/dashboard/logo")

        assert response.status_code == 404
        assert response.json()["error"] == "Logo not found"


class TestDashboardMaterialsCoverage:
    def test_folder_path_returns_none_for_unknown_key(self, monkeypatch, isolated_server):
        monkeypatch.setattr(materials_routes, "_workspace_base", lambda: isolated_server)

        assert materials_routes._folder_path("unknown-folder") is None

    def test_materials_file_route_handles_errors_and_success(self, monkeypatch, isolated_server):
        monkeypatch.setattr(materials_routes, "_workspace_base", lambda: isolated_server)
        resume_folder = isolated_server / materials_routes._FOLDERS["optimized_resumes"][0]
        resume_folder.mkdir(parents=True, exist_ok=True)
        pdf_folder = isolated_server / materials_routes._FOLDERS["resume_pdfs"][0]
        pdf_folder.mkdir(parents=True, exist_ok=True)
        pdf_path = pdf_folder / "resume.pdf"
        pdf_path.write_text("pdf-body", encoding="utf-8")

        with pytest.raises(HTTPException) as unknown_exc:
            asyncio.run(materials_routes.materials_file("unknown-folder", "resume.txt"))
        with pytest.raises(HTTPException) as missing_exc:
            asyncio.run(materials_routes.materials_file("optimized_resumes", "missing.txt"))
        with pytest.raises(HTTPException) as escape_exc:
            asyncio.run(materials_routes.materials_file("optimized_resumes", "../escape.txt"))

        response = asyncio.run(materials_routes.materials_file("resume_pdfs", "resume.pdf"))

        assert unknown_exc.value.status_code == 404
        assert "Unknown folder" in unknown_exc.value.detail
        assert missing_exc.value.status_code == 404
        assert "File not found" in missing_exc.value.detail
        assert escape_exc.value.status_code == 404
        assert escape_exc.value.detail == "Invalid file path"
        assert response.path == pdf_path
        assert response.media_type == "application/pdf"


class TestDashboardPeopleCoverage:
    def test_people_payload_sorts_recency_and_builds_follow_up_queue(self, monkeypatch):
        monkeypatch.setattr(
            people_routes,
            "_load_json",
            lambda *_args, **_kwargs: [
                {
                    "name": "Dana",
                    "company": "Acme",
                    "outreach_status": "sent",
                    "relationship": "recruiter",
                    "last_contacted": "2026-06-28",
                    "tags": ["warm"],
                },
                {
                    "name": "Eli",
                    "company": "Beta",
                    "outreach_status": "drafted",
                    "relationship": "manager",
                    "last_updated": "2026-06-27",
                },
                {
                    "name": "Fran",
                    "company": "Gamma",
                    "relationship": "peer",
                },
            ],
        )

        payload = people_routes._people_payload()

        assert payload["total"] == 3
        assert [person["name"] for person in payload["recent"]] == ["Dana", "Eli", "Fran"]
        assert [person["name"] for person in payload["follow_up_queue"]] == ["Dana", "Eli"]
        assert payload["by_status"][0] == {"status": "sent", "count": 1}
        assert {"relationship": "peer", "count": 1} in payload["by_relationship"]
        # full roster for client-side facet filtering (mobile Networking tab)
        assert [person["name"] for person in payload["people"]] == ["Dana", "Eli", "Fran"]


class TestDashboardPipelineCoverage:
    def test_safe_child_path_rejects_escape(self, isolated_server):
        safe_file = pipeline_routes._safe_child_path(isolated_server, "safe.txt")

        assert safe_file == (isolated_server / "safe.txt").resolve()

        with pytest.raises(HTTPException) as exc:
            pipeline_routes._safe_child_path(isolated_server, "../escape.txt")

        assert exc.value.status_code == 400
        assert exc.value.detail == "Invalid path"

    def test_pipeline_preview_template_rejects_unknown_template(self, http_client_noauth):
        response = http_client_noauth.get("/dashboard/pipeline/preview-template/not-real/navy")

        assert response.status_code == 400
        assert "Unknown template" in response.json()["detail"]

    def test_pipeline_preview_template_renders_master_resume_and_falls_back_style(
        self,
        http_client_noauth,
        isolated_server,
        monkeypatch,
    ):
        resume_path = isolated_server / "master_resume.txt"
        resume_path.write_text("MASTER CONTENT", encoding="utf-8")
        captured = {}

        monkeypatch.setattr(
            pipeline_routes.config,
            "get_active_master_resume_path",
            lambda: resume_path,
        )
        monkeypatch.setattr("lib.resume_parser._parse_resume_txt", lambda text: {"body": text})
        monkeypatch.setattr("lib.template_loader.VALID_TEMPLATES", {"modern"})
        monkeypatch.setattr("lib.template_loader.VALID_STYLES", {"navy"})
        monkeypatch.setattr(
            "lib.template_loader.render_resume",
            lambda data, template, style: captured.update(
                {"data": data, "template": template, "style": style}
            )
            or f"<html>{template}:{style}:{data['body']}:{data['footer_tag']}</html>",
        )

        response = http_client_noauth.get("/dashboard/pipeline/preview-template/modern/not-a-style")

        assert response.status_code == 200
        assert "modern:navy:MASTER CONTENT:SOFTWARE_ENGINEER" in response.text
        assert captured["template"] == "modern"
        assert captured["style"] == "navy"

    def test_pipeline_preview_template_uses_fallback_data_when_resume_missing(
        self,
        http_client_noauth,
        isolated_server,
        monkeypatch,
    ):
        missing_path = isolated_server / "missing_resume.txt"

        monkeypatch.setattr(
            pipeline_routes.config,
            "get_active_master_resume_path",
            lambda: missing_path,
        )
        monkeypatch.setattr("lib.template_loader.VALID_TEMPLATES", {"modern"})
        monkeypatch.setattr("lib.template_loader.VALID_STYLES", {"navy"})
        monkeypatch.setattr(
            "lib.template_loader.render_resume",
            lambda data, template, style: f"<html>{template}:{style}:{data['footer_tag']}:{data['contact']['email']}</html>",
        )

        response = http_client_noauth.get("/dashboard/pipeline/preview-template/modern/navy")

        assert response.status_code == 200
        assert "SOFTWARE_ENGINEER" in response.text
        assert "you@example.com" in response.text

    def test_pipeline_select_template_validates_and_saves(self, http_client_noauth, monkeypatch):
        updates = []
        monkeypatch.setattr("lib.template_loader.VALID_TEMPLATES", {"modern"})
        monkeypatch.setattr("lib.template_loader.VALID_STYLES", {"navy"})
        monkeypatch.setattr(
            pipeline_routes,
            "_update_job",
            lambda job_id, updater: updates.append(job_id) or updater({}),
        )

        success = http_client_noauth.post(
            "/dashboard/pipeline/select-template",
            json={"job_id": 5, "template": "modern", "style": "navy"},
        )
        bad_template = http_client_noauth.post(
            "/dashboard/pipeline/select-template",
            json={"job_id": 5, "template": "bad", "style": "navy"},
        )
        bad_style = http_client_noauth.post(
            "/dashboard/pipeline/select-template",
            json={"job_id": 5, "template": "modern", "style": "bad"},
        )

        assert success.status_code == 200
        assert success.json() == {"ok": True, "job_id": 5, "template": "modern", "style": "navy"}
        assert updates == [5]
        assert bad_template.status_code == 400
        assert "Unknown template" in bad_template.json()["detail"]
        assert bad_style.status_code == 400
        assert "Unknown style" in bad_style.json()["detail"]

    def test_pipeline_preview_cl_and_select_cl_template_cover_fallbacks(
        self,
        http_client_noauth,
        isolated_server,
        monkeypatch,
    ):
        cover_dir = isolated_server / "cover_letters"
        cover_dir.mkdir(parents=True, exist_ok=True)
        cover_path = cover_dir / "latest.txt"
        cover_path.write_text("Dear Hiring Team", encoding="utf-8")
        updates = []

        monkeypatch.setattr(
            pipeline_routes.config,
            "get_active_cover_letters_dir",
            lambda: cover_dir,
        )
        monkeypatch.setattr("lib.resume_parser._parse_cover_letter_txt", lambda text: {"paragraphs": [text]})
        monkeypatch.setattr("lib.template_loader.VALID_CL_TEMPLATES", {"modern"})
        monkeypatch.setattr("lib.template_loader.VALID_STYLES", {"navy"})
        monkeypatch.setattr(
            "lib.template_loader.render_cover_letter",
            lambda data, template, style: f"<html>{template}:{style}:{'|'.join(data['paragraphs'])}:{data['footer_tag']}</html>",
        )
        monkeypatch.setattr(
            pipeline_routes,
            "_update_job",
            lambda job_id, updater: updates.append(job_id) or updater({}),
        )

        preview = http_client_noauth.get("/dashboard/pipeline/preview-cl/modern/bad-style")
        select_ok = http_client_noauth.post(
            "/dashboard/pipeline/select-cl-template",
            json={"job_id": 6, "template": "modern", "style": "navy"},
        )
        select_bad_template = http_client_noauth.post(
            "/dashboard/pipeline/select-cl-template",
            json={"job_id": 6, "template": "bad", "style": "navy"},
        )
        select_bad_style = http_client_noauth.post(
            "/dashboard/pipeline/select-cl-template",
            json={"job_id": 6, "template": "modern", "style": "bad"},
        )

        assert preview.status_code == 200
        assert "modern:navy:Dear Hiring Team:SOFTWARE_ENGINEER" in preview.text
        assert select_ok.status_code == 200
        assert select_ok.json() == {"ok": True, "job_id": 6, "template": "modern", "style": "navy"}
        assert updates == [6]
        assert select_bad_template.status_code == 400
        assert "Unknown CL template" in select_bad_template.json()["detail"]
        assert select_bad_style.status_code == 400
        assert "Unknown style" in select_bad_style.json()["detail"]

    def test_pipeline_preview_cl_uses_fallback_data_when_no_letters_exist(
        self,
        http_client_noauth,
        isolated_server,
        monkeypatch,
    ):
        empty_dir = isolated_server / "empty_cover_letters"
        empty_dir.mkdir(parents=True, exist_ok=True)

        monkeypatch.setattr(
            pipeline_routes.config,
            "get_active_cover_letters_dir",
            lambda: empty_dir,
        )
        monkeypatch.setattr("lib.template_loader.VALID_CL_TEMPLATES", {"modern"})
        monkeypatch.setattr("lib.template_loader.VALID_STYLES", {"navy"})
        monkeypatch.setattr(
            "lib.template_loader.render_cover_letter",
            lambda data, template, style: f"<html>{template}:{style}:{data['paragraphs'][0]}:{data['footer_tag']}</html>",
        )

        response = http_client_noauth.get("/dashboard/pipeline/preview-cl/modern/navy")

        assert response.status_code == 200
        assert "Dear Hiring Manager" in response.text
        assert "SOFTWARE_ENGINEER" in response.text


def test_home_shows_readiness_from_synced_rows_on_desktop(monkeypatch, tmp_path):
    """Oura deprecated PATs: desktop readiness can arrive purely via cloud
    sync (oura_readiness rows, no local token) and must still power Home."""
    import datetime

    from transport.http.routes.dashboard import api as dash_api

    monkeypatch.setenv("DEPLOY_MODE", "desktop")
    monkeypatch.setattr(dash_api, "_oura_status", lambda: {"connected": False})
    monkeypatch.setattr(
        dash_api, "_load_oura",
        lambda: {"date": datetime.date.today().isoformat(), "readiness_score": 82,
                 "sleep_score": 78, "hrv": 45, "recovery_index": 70},
    )
    assert dash_api._oura_via_sync() is True

    # Stale rows don't count as connected.
    monkeypatch.setattr(
        dash_api, "_load_oura",
        lambda: {"date": "2020-01-01", "readiness_score": 82, "sleep_score": 78,
                 "hrv": 45, "recovery_index": 70},
    )
    assert dash_api._oura_via_sync() is False
