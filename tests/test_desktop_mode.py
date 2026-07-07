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


# ── AI provider settings (BYOK) ───────────────────────────────────────────────

@pytest.fixture()
def desktop_config(monkeypatch, tmp_path):
    """Point desktop config writes at a temp config.json."""
    path = tmp_path / "config.json"
    monkeypatch.setenv("JOBCONTEXT_CONFIG", str(path))
    return path


def test_ai_provider_get_reports_providers(desktop_client, desktop_config):
    resp = desktop_client.get("/desktop/ai-provider")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body["providers"]) == {"openai", "anthropic", "ollama"}
    assert body["providers"]["anthropic"]["has_key"] is False
    assert "running" in body["providers"]["ollama"]


def test_ai_provider_save_persists_and_applies(desktop_client, desktop_config, monkeypatch):
    # Deploy-pipeline test env sets LLM_PROVIDER=foundry, which outranks the
    # config this test writes — clear it so the save is what's asserted.
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    resp = desktop_client.post(
        "/desktop/ai-provider",
        json={"provider": "anthropic", "api_key": "sk-ant-test123", "model": "claude-opus-4-8"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "saved"
    # (body["model"] comes from get_llm_client, which conftest stubs offline —
    # the live-model path is covered by test_anthropic_provider_branch.)

    # Persisted to the desktop config file…
    stored = json.loads(desktop_config.read_text(encoding="utf-8"))
    assert stored["llm_provider"] == "anthropic"
    assert stored["anthropic_api_key"] == "sk-ant-test123"
    assert stored["anthropic_model"] == "claude-opus-4-8"

    # …and visible live without a restart (GET re-derives from runtime config).
    info = desktop_client.get("/desktop/ai-provider").json()
    assert info["provider"] == "anthropic"
    assert info["providers"]["anthropic"]["has_key"] is True
    # Key is never echoed anywhere in the payload.
    assert "sk-ant-test123" not in json.dumps(info)


def test_ai_provider_key_validation(desktop_client, desktop_config):
    resp = desktop_client.post(
        "/desktop/ai-provider",
        json={"provider": "anthropic", "api_key": "not-a-key"},
    )
    assert resp.status_code == 422

    assert desktop_client.post(
        "/desktop/ai-provider", json={"provider": "emacs"}
    ).status_code == 404


def test_ai_provider_empty_key_keeps_existing(desktop_client, desktop_config):
    desktop_client.post(
        "/desktop/ai-provider", json={"provider": "openai", "api_key": "sk-first"}
    )
    # Switching model only (blank key) must not clobber the stored key.
    desktop_client.post(
        "/desktop/ai-provider", json={"provider": "openai", "model": "gpt-4o"}
    )
    stored = json.loads(desktop_config.read_text(encoding="utf-8"))
    assert stored["openai_api_key"] == "sk-first"
    assert stored["openai_model"] == "gpt-4o"

    # clear_key removes it.
    desktop_client.post(
        "/desktop/ai-provider", json={"provider": "openai", "clear_key": True}
    )
    stored = json.loads(desktop_config.read_text(encoding="utf-8"))
    assert "openai_api_key" not in stored


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


def test_parent_watchdog_exits_on_stdin_eof(tmp_path):
    """--parent-watchdog: backend exits when the shell's stdin pipe closes.

    This is the anti-orphan guarantee — covers shell SIGTERM/SIGKILL/crash,
    none of which fire Tauri's exit handler. Full-process test on purpose:
    it exercises the real uvicorn shutdown path, not just the thread.
    """
    import subprocess

    proc = subprocess.Popen(
        [sys.executable, "desktop_main.py", "--parent-watchdog", "--data-dir", str(tmp_path / "wd")],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        cwd=str(Path(__file__).resolve().parent.parent),
    )
    try:
        port_line = proc.stdout.readline().strip()
        assert port_line.startswith("JOBCONTEXT_PORT=")
        proc.stdin.close()  # simulate parent death: OS closes the pipe
        assert proc.wait(timeout=30) == 0
    finally:
        if proc.poll() is None:
            proc.kill()


def test_config_loader_respects_env_path(monkeypatch, tmp_path):
    import lib.config as config_module

    external = tmp_path / "external-config.json"
    external.write_text(json.dumps({"name": "desktop-test"}), encoding="utf-8")
    monkeypatch.setenv("JOBCONTEXT_CONFIG", str(external))

    paths = config_module._config_search_paths()
    assert paths[0] == external
    assert config_module._load_config().get("name") == "desktop-test"


# ── workspace export / import ─────────────────────────────────────────────────

def _make_export_zip(entries: dict[str, bytes]) -> bytes:
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buf.getvalue()


@pytest.fixture()
def desktop_data_dir_env(monkeypatch, tmp_path):
    data_dir = tmp_path / "appdata"
    data_dir.mkdir()
    (data_dir / "config.json").write_text('{"llm_provider": "old"}')
    (data_dir / "db").mkdir()
    (data_dir / "db" / "jobcontextmcp.db").write_bytes(b"old-db")
    monkeypatch.setenv("JOBCONTEXT_DATA_DIR", str(data_dir))
    return data_dir


def test_export_workspace_zips_data_dir(desktop_client, desktop_data_dir_env):
    import io
    import zipfile

    resp = desktop_client.get("/api/dashboard/export")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        names = set(zf.namelist())
    assert "config.json" in names
    assert "db/jobcontextmcp.db" in names


def test_import_workspace_replaces_and_backs_up(desktop_client, desktop_data_dir_env):
    payload = _make_export_zip({
        "config.json": b'{"llm_provider": "imported"}',
        "db/jobcontextmcp.db": b"new-db",
        "workspace/01-Current-Optimized/resume.md": b"hi",
    })
    resp = desktop_client.post(
        "/desktop/import-workspace", content=payload,
        headers={"Content-Type": "application/zip"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "imported"
    assert body["restart_required"] is True
    assert (desktop_data_dir_env / "config.json").read_text() == '{"llm_provider": "imported"}'
    assert (desktop_data_dir_env / "db" / "jobcontextmcp.db").read_bytes() == b"new-db"
    backup = Path(body["backup"])
    assert backup.is_dir()
    assert (backup / "config.json").read_text() == '{"llm_provider": "old"}'


def test_import_workspace_accepts_single_top_folder(desktop_client, desktop_data_dir_env):
    payload = _make_export_zip({
        "jobContext/config.json": b"{}",
        "jobContext/db/jobcontextmcp.db": b"x",
    })
    resp = desktop_client.post(
        "/desktop/import-workspace", content=payload,
        headers={"Content-Type": "application/zip"},
    )
    assert resp.status_code == 200, resp.text
    assert (desktop_data_dir_env / "db" / "jobcontextmcp.db").read_bytes() == b"x"


def test_import_workspace_rejects_garbage(desktop_client, desktop_data_dir_env):
    resp = desktop_client.post(
        "/desktop/import-workspace", content=b"definitely not a zip",
        headers={"Content-Type": "application/zip"},
    )
    assert resp.status_code == 422
    # Nothing was touched.
    assert (desktop_data_dir_env / "config.json").read_text() == '{"llm_provider": "old"}'


def test_import_workspace_rejects_non_export_zip(desktop_client, desktop_data_dir_env):
    payload = _make_export_zip({"random.txt": b"hello"})
    resp = desktop_client.post(
        "/desktop/import-workspace", content=payload,
        headers={"Content-Type": "application/zip"},
    )
    assert resp.status_code == 422
    assert (desktop_data_dir_env / "config.json").read_text() == '{"llm_provider": "old"}'


def test_import_workspace_rejects_zip_slip(desktop_client, desktop_data_dir_env, tmp_path):
    payload = _make_export_zip({
        "config.json": b"{}",
        "../evil.txt": b"escape",
    })
    resp = desktop_client.post(
        "/desktop/import-workspace", content=payload,
        headers={"Content-Type": "application/zip"},
    )
    assert resp.status_code == 422
    assert not (tmp_path / "evil.txt").exists()
    assert (desktop_data_dir_env / "config.json").read_text() == '{"llm_provider": "old"}'


def test_import_route_absent_outside_desktop_mode(http_client_noauth):
    resp = http_client_noauth.post("/desktop/import-workspace", content=b"x")
    assert resp.status_code in (404, 405)


# ── Oura PAT connect endpoint ─────────────────────────────────────────────────

def test_oura_pat_endpoint_validates_and_saves(desktop_client, desktop_data_dir_env, monkeypatch):
    import tools.oura as oura

    saved = {}
    monkeypatch.setattr(oura, "validate_oura_pat", lambda tok: True)
    monkeypatch.setattr(oura, "save_oura_pat", lambda tok: saved.setdefault("pat", tok))
    monkeypatch.setattr(oura, "sync_oura", lambda: {"ok": True, "connected": True})

    resp = desktop_client.post("/api/dashboard/oura/pat", json={"token": " pat-xyz "})
    assert resp.status_code == 200, resp.text
    assert resp.json()["ouraConnected"] is True
    assert saved["pat"] == "pat-xyz"


def test_oura_pat_endpoint_rejects_bad_token(desktop_client, desktop_data_dir_env, monkeypatch):
    import tools.oura as oura

    monkeypatch.setattr(oura, "validate_oura_pat", lambda tok: False)
    resp = desktop_client.post("/api/dashboard/oura/pat", json={"token": "nope"})
    assert resp.status_code == 422

    resp = desktop_client.post("/api/dashboard/oura/pat", json={"token": "  "})
    assert resp.status_code == 422


def test_export_refused_without_user_partition_outside_desktop(http_client_noauth):
    """Cloud API-key sessions have no per-user data root; export must refuse
    rather than fall back to the global DATA_FOLDER (all tenants)."""
    resp = http_client_noauth.get("/api/dashboard/export")
    assert resp.status_code == 403


def test_import_workspace_allows_real_world_filenames(desktop_client, desktop_data_dir_env):
    """The zip-slip allowlist must not over-reject legitimately named user
    files (spaces, parens, apostrophes, unicode)."""
    payload = _make_export_zip({
        "config.json": b"{}",
        "db/jobcontextmcp.db": b"x",
        "workspace/06-Reference-Materials/Frank's resume (v2, final) #1 @draft.pdf": b"pdf",
    })
    resp = desktop_client.post(
        "/desktop/import-workspace", content=payload,
        headers={"Content-Type": "application/zip"},
    )
    assert resp.status_code == 200, resp.text
    assert (desktop_data_dir_env / "workspace" / "06-Reference-Materials" /
            "Frank's resume (v2, final) #1 @draft.pdf").read_bytes() == b"pdf"


def test_import_workspace_rejects_absolute_and_backslash_paths(desktop_client, desktop_data_dir_env):
    for evil in ("/etc/passwd", "db\\..\\..\\evil.db"):
        payload = _make_export_zip({"config.json": b"{}", evil: b"nope"})
        resp = desktop_client.post(
            "/desktop/import-workspace", content=payload,
            headers={"Content-Type": "application/zip"},
        )
        assert resp.status_code == 422, evil
