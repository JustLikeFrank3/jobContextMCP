import datetime as dt
import importlib
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from transport.http.app import create_app
from transport.http.config import reset_settings_cache
from transport.http.routes.dashboard import home as home_routes
from transport.http.routes.dashboard import interviews as interviews_routes
from transport.http.routes.dashboard import login as login_routes
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
        assert 'name="next" value="/dashboard"' in response.text
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
        assert response.headers["location"] == "/dashboard/login?next=/dashboard"

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
        assert "7</span>" in response.text
        assert "&#9888; 1 overdue" in response.text
        assert "2 to evaluate" in response.text
        assert "Review: Beta Corp" in response.text
        assert "Interviews" in response.text


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
