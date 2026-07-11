# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the jobContext desktop backend sidecar.

Build (from repo root):
    pyinstaller packaging/pyinstaller/jobcontext-backend.spec --noconfirm

Produces a onedir bundle (dist/jobcontext-backend/) — onedir over onefile
for faster startup and because macOS notarization needs every Mach-O in the
bundle individually signable.

Verify any build with the built-in diagnostics:
    dist/jobcontext-backend/jobcontext-backend --selftest

Known packaging hotspots handled here:
  - tiktoken resolves encodings through the tiktoken_ext namespace plugin,
    which static analysis can't see → explicit hiddenimports.
  - templates/ and the built React SPA (frontend/dist) are data files the
    code resolves relative to the bundle root (lib/app_dirs.resource_root).
  - WeasyPrint's Pango/Cairo/etc. native libraries are collected by the
    pyinstaller-hooks-contrib hook from the build machine's install
    (Homebrew / MSYS2 GTK / distro packages) — the CI build machine must
    have them installed.
"""
import os
import sys

ROOT = os.path.abspath(os.path.join(SPECPATH, "..", ".."))  # noqa: F821 — SPECPATH is a PyInstaller global

datas = [
    (os.path.join(ROOT, "templates"), "templates"),
    (os.path.join(ROOT, "frontend", "dist"), os.path.join("frontend", "dist")),
    # Favicons/og-images served by transport/http/app.py from a path relative
    # to the module — must travel into the bundle or every browser/webview
    # favicon request errors in the frozen app (Windows field report).
    (os.path.join(ROOT, "transport", "http", "static"), os.path.join("transport", "http", "static")),
]

hiddenimports = [
    "tiktoken_ext",
    "tiktoken_ext.openai_public",
]

a = Analysis(
    [os.path.join(ROOT, "desktop_main.py")],
    pathex=[ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[os.path.join(SPECPATH, "hooks")],  # noqa: F821
    runtime_hooks=[
        # Makes the bundled Pango/GObject dylibs win over any system/Homebrew
        # copies at run time (see the rthook's docstring for the full story).
        os.path.join(SPECPATH, "rthooks", "pyi_rth_weasyprint_libs.py"),  # noqa: F821
    ],
    excludes=[
        # dev/test-only weight
        "pytest",
        "IPython",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="jobcontext-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,  # sidecar: stdout carries JOBCONTEXT_PORT=<port>
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="jobcontext-backend",
)

# ── macOS post-processing: bind the WeasyPrint stack to its own dir ──────────
# PyInstaller rewrites the collected dylibs' rpath to @loader_path/.. (the
# _internal root), where dedup may have left same-named libraries from other
# packages (Pillow vendors its own harfbuzz). Pango resolving harfbuzz to
# Pillow's build while WeasyPrint dlopens the Homebrew one SIGBUSes the
# moment an hb_face_t crosses images. Rewriting intra-directory deps to
# @loader_path/<name> pins every weasyprint_libs dylib to its siblings,
# independent of rpath search order; ad-hoc re-sign afterwards (arm64
# requires valid signatures; sign every Mach-O, roadmap Phase 7 note).
if sys.platform == "darwin":
    import glob
    import subprocess

    _wl_dir = os.path.join(DISTPATH, "jobcontext-backend", "_internal", "weasyprint_libs")  # noqa: F821
    _wl_libs = glob.glob(os.path.join(_wl_dir, "*.dylib"))
    _wl_names = {os.path.basename(p) for p in _wl_libs}
    for _lib in _wl_libs:
        _deps = subprocess.run(
            ["otool", "-L", _lib], capture_output=True, text=True, check=True
        ).stdout.splitlines()[1:]
        for _line in _deps:
            _dep = _line.strip().split(" ")[0]
            _base = os.path.basename(_dep)
            if _dep.startswith("@rpath/") and _base in _wl_names:
                subprocess.run(
                    ["install_name_tool", "-change", _dep, f"@loader_path/{_base}", _lib],
                    check=True, capture_output=True,
                )
        subprocess.run(["codesign", "-f", "-s", "-", _lib], check=True, capture_output=True)
    print(f"weasyprint_libs: rebound {len(_wl_libs)} dylibs to @loader_path siblings")
