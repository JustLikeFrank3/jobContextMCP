"""The LaTeX compilers must run in a hardened, untrusted-input mode.

Tenant-supplied section content (write_latex_section) and cover-letter bodies
are compiled by tectonic/pdflatex. Without hardening, LaTeX such as
``\\input{/proc/self/environ}`` could read pod files (secrets, the
service-account token) or other tenants' data into the produced PDF. tectonic
must get ``--untrusted``; the pdflatex fallback must get ``-no-shell-escape``
and paranoid openin/openout. These tests assert the flags reach subprocess.
"""
from __future__ import annotations

from types import SimpleNamespace

from tools import latex_export


def _capture_run(recorded):
    def fake_run(cmd, *args, **kwargs):
        recorded.append((list(cmd), kwargs.get("env") or {}))
        cwd = kwargs["cwd"]
        # produce whatever PDF the caller expects
        for name in ("cover_letter.pdf", "resume.pdf"):
            (latex_export.Path(cwd) / name).write_bytes(b"%PDF")
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    return fake_run


def test_tectonic_runs_untrusted(monkeypatch, tmp_path):
    latex_dir = tmp_path / "latex"
    latex_dir.mkdir()
    (latex_dir / "_header.tex").write_text("", encoding="utf-8")
    (latex_dir / "TLCresume.sty").write_text("", encoding="utf-8")
    recorded: list = []

    monkeypatch.setattr(latex_export, "_latex_dir", lambda: latex_dir)
    monkeypatch.setattr(latex_export.cfg, "RESUME_FOLDER", tmp_path / "resumes")
    (tmp_path / "resumes").mkdir()
    monkeypatch.setattr(latex_export, "_tectonic_bin", lambda: "/usr/bin/tectonic")
    monkeypatch.setattr(latex_export.subprocess, "run", _capture_run(recorded))

    latex_export.generate_cover_letter_latex(body="Hi.", company="Acme", role="Eng")

    cmd, env = recorded[-1]
    assert cmd[0] == "/usr/bin/tectonic"
    assert "--untrusted" in cmd
    assert env.get("TECTONIC_UNTRUSTED_MODE") == "1"


def test_pdflatex_fallback_disables_shell_escape(monkeypatch, tmp_path):
    recorded: list = []

    def tectonic_fails(cmd, *args, **kwargs):
        if cmd[0] == "tectonic":
            return SimpleNamespace(returncode=1, stderr="no bundle", stdout="")
        recorded.append((list(cmd), kwargs.get("env") or {}))
        (latex_export.Path(kwargs["cwd"]) / "doc.pdf").write_bytes(b"%PDF")
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    monkeypatch.setattr(latex_export, "_tectonic_bin", lambda: "tectonic")
    monkeypatch.setattr(latex_export, "_pdflatex_bin", lambda: "/usr/bin/pdflatex")
    monkeypatch.setattr(latex_export.subprocess, "run", tectonic_fails)

    tex = tmp_path / "doc.tex"
    tex.write_text("\\documentclass{article}\\begin{document}x\\end{document}")
    latex_export._compile_tex(tex, tmp_path, tmp_path / "doc.pdf")

    assert recorded, "pdflatex fallback was not exercised"
    cmd, env = recorded[-1]
    assert cmd[0] == "/usr/bin/pdflatex"
    assert "-no-shell-escape" in cmd
    assert env.get("openin_any") == "p"
    assert env.get("openout_any") == "p"
