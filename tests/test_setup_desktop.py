"""setup_workspace on desktop must merge into the app-data config — never
write beside the (signed) executable or re-point the live process at it."""
from __future__ import annotations

import json

import pytest

import lib.config as cfg


@pytest.fixture()
def desktop_workspace(tmp_path, monkeypatch):
    from lib.user_provisioning import provision_user_data

    monkeypatch.setenv("DEPLOY_MODE", "desktop")
    monkeypatch.setenv("USE_SQLITE", "1")     # desktop parity: SQLite reads
    monkeypatch.setenv("SQLITE_ONLY", "1")
    import lib.io as lio
    monkeypatch.setattr(lio, "_USE_SQLITE", True)   # module constant read at import
    monkeypatch.setattr(lio, "_SQLITE_ONLY", True, raising=False)
    monkeypatch.setenv("JOBCONTEXT_CONFIG", str(tmp_path / "config.json"))
    monkeypatch.setenv("JOBCONTEXT_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(cfg, "DATA_FOLDER", tmp_path, raising=False)  # Path, like prod
    # Static module-level file constants were computed at import against the
    # real DATA_FOLDER — repoint every one this test touches (JOB_QUEUE_FILE
    # feeds get_job_queue's read path).
    monkeypatch.setattr(cfg, "JOB_QUEUE_FILE", tmp_path / "job_queue.json", raising=False)
    provision_user_data(tmp_path)
    # Pre-existing device config that MUST survive setup (keys, sync).
    (tmp_path / "config.json").write_text(json.dumps({
        "llm_provider": "anthropic",
        "anthropic_api_key": "sk-ant-KEEP-ME",
        "cloud_sync_pat": "pat-KEEP-ME",
        "data_folder": str(tmp_path),
    }))
    return tmp_path


def test_setup_merges_desktop_config_and_keeps_secrets(desktop_workspace, monkeypatch):
    import tools.setup as setup_mod

    result = setup_mod.setup_workspace(
        name="Frank MacBride",
        email="frank@example.com",
        phone="+1 555 0100",
        linkedin="linkedin.com/in/frank",
        city_state="Atlanta, GA",
        master_resume_content="# Frank MacBride\n\nEngineer.",
    )
    assert "SETUP COMPLETE" in result

    saved = json.loads((desktop_workspace / "config.json").read_text())
    assert saved["contact"]["name"] == "Frank MacBride"
    assert saved["anthropic_api_key"] == "sk-ant-KEEP-ME"   # never rebuilt
    assert saved["cloud_sync_pat"] == "pat-KEEP-ME"
    assert saved["data_folder"] == str(desktop_workspace)   # never re-pointed

    # Nothing written beside the "executable" (repo root in tests).
    assert not (setup_mod._HERE / "config.json").exists() or \
        "KEEP-ME" not in (setup_mod._HERE / "config.json").read_text()


def test_setup_leaves_live_data_folder_alone(desktop_workspace):
    import lib.db as db
    import tools.setup as setup_mod

    with db.get_connection() as con:
        con.execute(
            "INSERT INTO job_queue (company, role, jd, source, added_date, status) "
            "VALUES ('KeepCo', 'SWE', 'jd', 't', date('now'), 'pending')"
        )
    setup_mod.setup_workspace(
        name="Frank", email="f@x.com", phone="1", linkedin="l", city_state="ATL",
        master_resume_content="# Frank",
    )
    # The live process still reads the same data folder: no blank slate.
    from tools.job_queue import get_job_queue

    assert "KeepCo" in get_job_queue()
