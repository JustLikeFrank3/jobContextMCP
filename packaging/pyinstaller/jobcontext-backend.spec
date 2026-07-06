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

ROOT = os.path.abspath(os.path.join(SPECPATH, "..", ".."))  # noqa: F821 — SPECPATH is a PyInstaller global

datas = [
    (os.path.join(ROOT, "templates"), "templates"),
    (os.path.join(ROOT, "frontend", "dist"), os.path.join("frontend", "dist")),
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
    runtime_hooks=[],
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
