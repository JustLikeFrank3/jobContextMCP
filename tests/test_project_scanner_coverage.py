import subprocess
from pathlib import Path

import pytest

from tools import project_scanner as ps


def test_git_pull_and_clone_status_paths(isolated_server, monkeypatch, tmp_path):
    folder = tmp_path / "repo"
    folder.mkdir()

    monkeypatch.setattr(ps.subprocess, "run", lambda *a, **k: type("R", (), {"returncode": 0, "stdout": "ok", "stderr": ""})())
    assert ps._git_pull(folder) == "ok"

    monkeypatch.setattr(ps.subprocess, "run", lambda *a, **k: type("R", (), {"returncode": 1, "stdout": "", "stderr": "bad"})())
    assert ps._git_pull(folder).startswith("warning:")

    monkeypatch.setattr(ps.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(subprocess.TimeoutExpired(cmd="git", timeout=20)))
    assert "timed out" in ps._git_pull(folder)

    monkeypatch.setattr(ps.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError()))
    assert "git not found" in ps._clone_repo("https://x/repo.git", folder)


def test_file_matches_tech_variants(isolated_server):
    entry = {"filenames": ["dockerfile"], "exts": [".py"], "content": ["fastapi"]}
    assert ps._file_matches_tech(entry, ".txt", "dockerfile", "anything")
    assert not ps._file_matches_tech(entry, ".js", "app.js", "fastapi")
    assert ps._file_matches_tech(entry, ".py", "app.py", "import fastapi")

    all_entry = {"filenames": [], "exts": [".py"], "content_all": ["s3", "boto3"]}
    assert ps._file_matches_tech(all_entry, ".py", "x.py", "use s3 and boto3")
    assert not ps._file_matches_tech(all_entry, ".py", "x.py", "only s3")


def test_scan_folder_detects_tech_and_skips_unreadable_files(isolated_server, tmp_path):
    root = tmp_path / "scan"
    root.mkdir()
    (root / "api.py").write_text("from fastapi import FastAPI\n", encoding="utf-8")
    (root / "Dockerfile").write_text("FROM python:3.12\n", encoding="utf-8")
    (root / "bad.py").write_text("raise", encoding="utf-8")

    original_read = Path.read_text

    def fake_read(path, *a, **k):
        if str(path).endswith("bad.py"):
            raise PermissionError("nope")
        return original_read(path, *a, **k)

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(Path, "read_text", fake_read)
    try:
        tech, files = ps._scan_folder(root)
    finally:
        monkeypatch.undo()

    assert files >= 3
    assert "Python" in tech
    assert "FastAPI" in tech


def test_scan_project_for_skills_reports_new_and_cleans_temp(isolated_server, monkeypatch, tmp_path):
    local = tmp_path / "local"
    local.mkdir()

    monkeypatch.setattr(ps.config, "get_active_side_project_folders", lambda: [local])
    monkeypatch.setattr(ps.config, "get_active_side_project_repos", lambda: [{"url": "https://github.com/acme/repo.git", "branch": "main"}])
    monkeypatch.setattr(ps, "_git_pull", lambda _f: "Already up to date.")

    def fake_scan(folder):
        if folder == local:
            return {"Python", "FastAPI"}, 5
        return {"RAG / semantic search"}, 7

    monkeypatch.setattr(ps, "_scan_folder", fake_scan)
    monkeypatch.setattr(ps, "_load_master_context", lambda: "python")

    tmp_clone = tmp_path / "clone"
    monkeypatch.setattr(ps.tempfile, "mkdtemp", lambda prefix: str(tmp_clone))
    monkeypatch.setattr(ps, "_clone_repo", lambda *_a, **_k: "cloned ok")

    removed = []
    monkeypatch.setattr(ps.shutil, "rmtree", lambda p, ignore_errors=True: removed.append(str(p)))

    out = ps.scan_project_for_skills()
    assert "SIDE PROJECT SKILL SCAN" in out
    assert "★ NEW" in out
    assert "RAG / semantic search" in out
    assert any("clone" in p for p in removed)


def test_scan_project_for_skills_handles_missing_config(isolated_server, monkeypatch):
    monkeypatch.setattr(ps.config, "get_active_side_project_folders", lambda: [])
    monkeypatch.setattr(ps.config, "get_active_side_project_repos", lambda: [])
    assert "No side project folders or repos configured" in ps.scan_project_for_skills()


def test_scan_project_for_skills_emits_suggestion_bullets(isolated_server, monkeypatch, tmp_path):
    folder = tmp_path / "project"
    folder.mkdir()
    monkeypatch.setattr(ps.config, "get_active_side_project_folders", lambda: [folder])
    monkeypatch.setattr(ps.config, "get_active_side_project_repos", lambda: [])
    monkeypatch.setattr(ps, "_git_pull", lambda _f: "ok")
    monkeypatch.setattr(
        ps,
        "_scan_folder",
        lambda _f: (
            {
                "Raspberry Pi GPIO", "Pydantic", "Python async/await", "Azure Blob Storage",
                "HTTP Range requests", "systemd / Linux services", "WebSockets",
                "JWT authentication", "Model Context Protocol (MCP)", "WeasyPrint / PDF generation",
                "RAG / semantic search", "SQLite / aiosqlite", "Microsoft Entra ID (PKCE/OIDC)",
                "Kubernetes (K8s)", "GitHub Actions", "PostgreSQL", "Redis", "Apache Kafka",
                "LangChain", "OpenAI API", "Anthropic / Claude API", "gRPC", "GraphQL",
                "Terraform IaC", "Prometheus / Grafana", "LaTeX / Tectonic",
            },
            12,
        ),
    )
    monkeypatch.setattr(ps, "_load_master_context", lambda: "")

    out = ps.scan_project_for_skills()
    assert "Suggested Resume Bullets" in out
    assert "Built production MCP server" in out
    assert "Automated LaTeX/Tectonic" in out
