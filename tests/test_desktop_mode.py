"""Desktop deployment profile (DEPLOY_MODE=desktop).

Covers lib/app_dirs.py, the desktop HttpSettings profile, the /healthz
alias, the /desktop/shutdown route, and desktop_main bootstrap.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from lib.app_dirs import APP_NAME, desktop_data_dir, is_desktop_mode, resource_root


# ── lib/app_dirs ───────────────────────────────────────────────────────────────

def test_desktop_mode_flag(monkeypatch):
    monkeypatch.delenv("DEPLOY_MODE", raising=False)
    assert is_desktop_mode() is False
    monkeypatch.setenv("DEPLOY_MODE", "desktop")
    assert is_desktop_mode() is True
    monkeypatch.setenv("DEPLOY_MODE", "DESKTOP")
    assert is_desktop_mode() is True
    monkeypatch.setenv("DEPLOY_MODE", "aks")
    assert is_desktop_mode() is False


def test_data_dir_env_override_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("JOBCONTEXT_DATA_DIR", str(tmp_path / "custom"))
    assert desktop_data_dir() == tmp_path / "custom"


def test_data_dir_platform_default(monkeypatch):
    monkeypatch.delenv("JOBCONTEXT_DATA_DIR", raising=False)
    result = desktop_data_dir()
    assert result.is_absolute()
    assert result.name == APP_NAME
    if sys.platform == "darwin":
        assert "Application Support" in str(result)


def test_resource_root_source_checkout():
    # In a source checkout the resource root is the repo root.
    assert (resource_root() / "tools.json").exists()


def test_resource_root_frozen(monkeypatch):
    monkeypatch.setattr(sys, "_MEIPASS", "/tmp/_MEIxyz", raising=False)
    assert resource_root() == Path("/tmp/_MEIxyz")


# ── HttpSettings desktop profile ──────────────────────────────────────────────

@pytest.fixture()
def _settings_env(monkeypatch):
    from transport.http.config import reset_settings_cache
    for var in ("DEPLOY_MODE", "ENABLE_REMOTE", "HOST", "PORT", "API_KEY"):
        monkeypatch.delenv(var, raising=False)
    reset_settings_cache()
    yield monkeypatch
    reset_settings_cache()


def test_settings_desktop_mode(_settings_env):
    from transport.http.config import get_settings
    _settings_env.setenv("DEPLOY_MODE", "desktop")
    settings = get_settings()
    assert settings.desktop_mode is True
    assert settings.bind_host == "127.0.0.1"


def test_settings_desktop_ignores_enable_remote(_settings_env):
    from transport.http.config import get_settings
    _settings_env.setenv("DEPLOY_MODE", "desktop")
    _settings_env.setenv("ENABLE_REMOTE", "true")
    settings = get_settings()
    assert settings.enable_remote is False
    assert settings.bind_host == "127.0.0.1"


def test_settings_default_not_desktop(_settings_env):
    from transport.http.config import get_settings
    settings = get_settings()
    assert settings.desktop_mode is False


def test_settings_port_zero(_settings_env):
    from transport.http.config import get_settings
    _settings_env.setenv("PORT", "0")
    assert get_settings().port == 0


# ── /healthz alias ────────────────────────────────────────────────────────────

def test_healthz_alias(http_client_noauth):
    for path in ("/health", "/healthz"):
        resp = http_client_noauth.get(path)
        assert resp.status_code == 200
        assert "version" in resp.json()


# ── /desktop/shutdown route ───────────────────────────────────────────────────

@pytest.fixture()
def desktop_client(monkeypatch, isolated_server):
    from fastapi.testclient import TestClient
    from transport.http.app import create_app
    from transport.http.config import reset_settings_cache

    monkeypatch.setenv("DEPLOY_MODE", "desktop")
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.delenv("ENABLE_REMOTE", raising=False)
    reset_settings_cache()
    app = create_app()
    with TestClient(app) as client:
        yield client
    reset_settings_cache()


def test_shutdown_route_absent_outside_desktop_mode(http_client_noauth):
    resp = http_client_noauth.post("/desktop/shutdown")
    assert resp.status_code in (404, 405)


def test_shutdown_route_no_handler(desktop_client):
    from transport.http import desktop as desktop_runtime
    desktop_runtime.register_shutdown(None)
    resp = desktop_client.post("/desktop/shutdown")
    assert resp.status_code == 200
    assert resp.json()["status"] == "unavailable"


def test_shutdown_route_invokes_handler(desktop_client):
    from transport.http import desktop as desktop_runtime
    calls = []
    desktop_runtime.register_shutdown(lambda: calls.append(True))
    try:
        resp = desktop_client.post("/desktop/shutdown")
        assert resp.status_code == 200
        assert resp.json()["status"] == "shutting-down"
        assert calls == [True]
    finally:
        desktop_runtime.register_shutdown(None)


# ── one-click MCP client connect ──────────────────────────────────────────────

@pytest.fixture()
def fake_home(monkeypatch, tmp_path):
    """Point the MCP client registry at a temp home dir."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    if sys.platform not in ("darwin",) and os.name != "nt":
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    return home


def test_mcp_clients_detection(desktop_client, fake_home):
    from transport.http import desktop as desktop_runtime

    # "Install" Claude Desktop by creating its config dir with an existing config.
    claude_path = desktop_runtime._mcp_client_registry()["claude-desktop"]["path"]
    claude_path.parent.mkdir(parents=True)
    claude_path.write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}}), encoding="utf-8")

    resp = desktop_client.get("/desktop/mcp-clients")
    assert resp.status_code == 200
    clients = {c["id"]: c for c in resp.json()["clients"]}
    assert set(clients) == {"claude-desktop", "vscode", "cursor"}
    assert clients["claude-desktop"]["installed"] is True
    assert clients["claude-desktop"]["connected"] is False
    assert clients["cursor"]["installed"] is False


def test_mcp_connect_merges_preserving_existing(desktop_client, fake_home):
    from transport.http import desktop as desktop_runtime

    spec = desktop_runtime._mcp_client_registry()["claude-desktop"]
    path = spec["path"]
    path.parent.mkdir(parents=True)
    original = {"mcpServers": {"other": {"command": "x"}}, "theme": "dark"}
    path.write_text(json.dumps(original), encoding="utf-8")

    resp = desktop_client.post("/desktop/mcp-connect", json={"client": "claude-desktop"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "connected"

    written = json.loads(path.read_text(encoding="utf-8"))
    assert written["theme"] == "dark"                      # untouched keys survive
    assert written["mcpServers"]["other"] == {"command": "x"}
    entry = written["mcpServers"]["jobcontext"]
    assert entry["args"][-1] == "--mcp-stdio"
    assert path.with_suffix(".json.bak").exists()          # previous version backed up

    # Detection now reports connected.
    clients = {c["id"]: c for c in desktop_client.get("/desktop/mcp-clients").json()["clients"]}
    assert clients["claude-desktop"]["connected"] is True


def test_mcp_connect_vscode_uses_typed_servers_key(desktop_client, fake_home):
    from transport.http import desktop as desktop_runtime

    resp = desktop_client.post("/desktop/mcp-connect", json={"client": "vscode"})
    assert resp.status_code == 200

    path = desktop_runtime._mcp_client_registry()["vscode"]["path"]
    written = json.loads(path.read_text(encoding="utf-8"))
    entry = written["servers"]["jobcontext"]
    assert entry["type"] == "stdio"


def test_mcp_connect_unknown_client(desktop_client, fake_home):
    resp = desktop_client.post("/desktop/mcp-connect", json={"client": "emacs"})
    assert resp.status_code == 404


def test_mcp_routes_absent_outside_desktop_mode(http_client_noauth):
    assert http_client_noauth.get("/desktop/mcp-clients").status_code in (404, 405)


# ── desktop_main bootstrap ────────────────────────────────────────────────────

def test_bootstrap_first_run_creates_layout(tmp_path):
    import desktop_main

    app_dir = tmp_path / "jobContext"
    app_dir.mkdir()
    config_path = desktop_main.bootstrap(app_dir)

    assert config_path == app_dir / "config.json"
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    assert cfg["data_folder"] == str(app_dir)
    assert cfg["resume_folder"] == str(app_dir / "workspace")
    assert cfg["leetcode_folder"] == str(app_dir / "workspace" / "leetcode")
    assert "contact" in cfg  # starter contact block from provisioning

    assert (app_dir / "db" / "jobcontextmcp.db").is_file()
    assert (app_dir / "workspace" / "01-Current-Optimized").is_dir()
    master = app_dir / "workspace" / "01-Current-Optimized" / "Resume - MASTER SOURCE.txt"
    assert master.is_file()


def test_bootstrap_idempotent_preserves_user_edits(tmp_path):
    import desktop_main

    app_dir = tmp_path / "jobContext"
    app_dir.mkdir()
    config_path = desktop_main.bootstrap(app_dir)

    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    cfg["openai_api_key"] = "sk-user-added"
    cfg["contact"]["name"] = "Frank"
    config_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    desktop_main.bootstrap(app_dir)

    cfg2 = json.loads(config_path.read_text(encoding="utf-8"))
    assert cfg2["openai_api_key"] == "sk-user-added"
    assert cfg2["contact"]["name"] == "Frank"
    assert cfg2["data_folder"] == str(app_dir)


def test_apply_desktop_env(monkeypatch, tmp_path):
    import desktop_main

    monkeypatch.setenv("ENABLE_REMOTE", "true")
    monkeypatch.setenv("ENTRA_TENANT_ID", "t")
    monkeypatch.setenv("ENTRA_CLIENT_ID", "c")
    # _apply_desktop_env writes os.environ directly; setenv-then-delenv makes
    # monkeypatch snapshot the pre-test (absent) state so teardown removes
    # whatever the function sets, instead of leaking USE_SQLITE=1 etc. into
    # later tests.
    for var in ("DEPLOY_MODE", "USE_SQLITE", "SQLITE_ONLY", "JOBCONTEXT_CONFIG"):
        monkeypatch.setenv(var, "pre-test-sentinel")
        monkeypatch.delenv(var)

    import os
    desktop_main._apply_desktop_env(tmp_path)

    assert os.environ["DEPLOY_MODE"] == "desktop"
    assert os.environ["USE_SQLITE"] == "1"
    assert os.environ["SQLITE_ONLY"] == "1"
    assert os.environ["JOBCONTEXT_CONFIG"] == str(tmp_path / "config.json")
    for var in ("ENABLE_REMOTE", "ENTRA_TENANT_ID", "ENTRA_CLIENT_ID"):
        assert var not in os.environ


def test_config_loader_respects_env_path(monkeypatch, tmp_path):
    import lib.config as config_module

    external = tmp_path / "external-config.json"
    external.write_text(json.dumps({"name": "desktop-test"}), encoding="utf-8")
    monkeypatch.setenv("JOBCONTEXT_CONFIG", str(external))

    paths = config_module._config_search_paths()
    assert paths[0] == external
    assert config_module._load_config().get("name") == "desktop-test"
