"""Desktop packaging checks report every failure and return an accurate exit code."""
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize("failed", [
    frozenset(),
    frozenset({"config"}),
    frozenset({"sqlite"}),
    frozenset({"tools"}),
    frozenset({"templates"}),
    frozenset({"pdf"}),
    frozenset({"config", "sqlite", "tools", "templates", "pdf"}),
])
def test_selftest_aggregates_all_packaging_results(failed, monkeypatch, tmp_path, capsys):
    import desktop_main
    import lib.config
    import lib.db
    import lib.template_loader
    import server
    import weasyprint

    app_dir = tmp_path / "app"
    monkeypatch.setattr(lib.config, "DATA_FOLDER", app_dir / "wrong" if "config" in failed else app_dir)
    database = SimpleNamespace(execute=lambda _sql: SimpleNamespace(
        fetchone=lambda: (0 if "sqlite" in failed else 12,),
    ))
    monkeypatch.setattr(lib.db, "get_connection", lambda: nullcontext(database))
    monkeypatch.setattr(server, "_TOOL_MODULES", [] if "tools" in failed else list(range(21)))
    monkeypatch.setattr(lib.template_loader, "list_templates", lambda: [] if "templates" in failed else ["modern"])

    def write_pdf(path):
        Path(path).write_bytes(b"PDF" if "pdf" in failed else b"PDF" * 200)

    monkeypatch.setattr(weasyprint, "HTML", lambda **_kwargs: SimpleNamespace(write_pdf=write_pdf))

    assert desktop_main._selftest(app_dir) == (1 if failed else 0)
    lines = capsys.readouterr().out.splitlines()
    for name in ("config", "sqlite", "tools", "templates", "pdf"):
        expected = "FAIL" if name in failed else "PASS"
        assert sum(line.startswith(f"{expected} {name}") for line in lines) == 1
    assert lines[-1] == (f"SELFTEST FAIL ({len(failed)})" if failed else "SELFTEST PASS")
