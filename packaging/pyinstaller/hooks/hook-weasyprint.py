"""Project hook for WeasyPrint — replaces the pyinstaller-hooks-contrib hook.

Why: the stock hook finds Pango/GObject/HarfBuzz via ctypes.util.find_library(),
which on macOS only searches Homebrew's lib dir when running a Homebrew-patched
Python. GitHub Actions runners use hostedtoolcache CPython, so collection
silently came up empty and the frozen app failed at runtime (observed on
macos-14, 2026-07-06). This hook keeps the stock behaviour (find_library +
fontconfig data) and, on macOS, additionally collects the required dylib
families straight from the Homebrew prefix.

PyInstaller uses only the first hook found per module, so this file must be
self-contained rather than extending the contrib hook.
"""
import ctypes.util
import glob
import os
import subprocess  # nosec B404 — used only to ask `brew --prefix` at build time
from pathlib import Path

from PyInstaller.compat import is_darwin, is_win
from PyInstaller.depend.utils import _resolveCtypesImports
from PyInstaller.utils.hooks import collect_data_files, logger

datas = collect_data_files("weasyprint")
binaries = []
fontconfig_config_dir_found = False

_FONTCONFIG_NAMES = [
    "fontconfig-1", "fontconfig", "libfontconfig",
    "libfontconfig-1.dll", "libfontconfig.so.1", "libfontconfig-1.dylib",
]
_LIB_NAMES = [
    "gobject-2.0-0", "gobject-2.0", "libgobject-2.0-0", "libgobject-2.0.so.0", "libgobject-2.0.dylib",
    "pango-1.0-0", "pango-1.0", "libpango-1.0-0", "libpango-1.0.so.0", "libpango-1.0.dylib",
    "pangocairo-1.0-0", "pangocairo-1.0", "libpangocairo-1.0-0", "libpangocairo-1.0.so.0",
    "libpangocairo-1.0.dylib",
    "harfbuzz", "harfbuzz-0.0", "libharfbuzz-0", "libharfbuzz.so.0", "libharfbuzz.0.dylib",
    "harfbuzz-subset", "harfbuzz-subset-0.0", "libharfbuzz-subset-0", "libharfbuzz-subset.so.0",
    "libharfbuzz-subset.0.dylib", "libharfbuzz-subset-0.dll",
    "pangoft2-1.0-0", "pangoft2-1.0", "libpangoft2-1.0-0", "libpangoft2-1.0.so.0", "libpangoft2-1.0.dylib",
]

# Dylib families WeasyPrint dlopens (directly or transitively) — collected
# from the Homebrew prefix on macOS regardless of find_library behaviour.
_DARWIN_LIB_FAMILIES = [
    "gobject-2.0", "glib-2.0", "gio-2.0", "gmodule-2.0", "gthread-2.0",
    "pango-1.0", "pangocairo-1.0", "pangoft2-1.0", "cairo", "cairo-gobject",
    "harfbuzz", "harfbuzz-subset", "fontconfig", "freetype", "fribidi",
    "gdk_pixbuf-2.0", "intl", "ffi", "pcre2-8", "graphite2",
]


def _brew_prefix() -> str:
    prefix = os.environ.get("HOMEBREW_PREFIX", "").strip()
    if prefix:
        return prefix
    try:
        return subprocess.run(  # nosec B603 B607
            ["brew", "--prefix"], capture_output=True, text=True, check=True, timeout=30
        ).stdout.strip()
    except Exception:
        return "/opt/homebrew" if os.path.isdir("/opt/homebrew/lib") else "/usr/local"


try:
    lib_basenames = []
    for lib in _LIB_NAMES:
        libname = ctypes.util.find_library(lib)
        if libname is not None:
            lib_basenames.append(os.path.basename(libname))
    for lib in _FONTCONFIG_NAMES:
        libname = ctypes.util.find_library(lib)
        if libname is not None:
            lib_basenames.append(os.path.basename(libname))
            # On Windows (GTK/MSYS2 install), ship its fontconfig config too.
            if is_win:
                fontconfig_config_dir = Path(libname).parent.parent / "etc/fonts"
                if fontconfig_config_dir.is_dir():
                    datas.append((str(fontconfig_config_dir), "etc/fonts"))
                    fontconfig_config_dir_found = True
    if lib_basenames:
        for resolved_lib in _resolveCtypesImports(lib_basenames):
            binaries.append((resolved_lib[1], "."))

    if is_darwin:
        collected = {os.path.basename(src) for src, _dest in binaries}
        lib_dir = os.path.join(_brew_prefix(), "lib")
        for family in _DARWIN_LIB_FAMILIES:
            for path in glob.glob(os.path.join(lib_dir, f"lib{family}*.dylib")):
                if os.path.basename(path) not in collected:
                    binaries.append((path, "."))
                    collected.add(os.path.basename(path))

    fontconfig_config_dir = Path("/etc/fonts")
    if fontconfig_config_dir.is_dir():
        datas.append((str(fontconfig_config_dir), "etc/fonts"))
        fontconfig_config_dir_found = True
except Exception as exc:  # noqa: BLE001 — mirror stock hook's resilience
    logger.warning("Error while trying to find system-installed depending libraries: %s", exc)

if not binaries:
    logger.warning("Depending libraries not found - weasyprint will likely fail to work!")
if not fontconfig_config_dir_found:
    logger.warning(
        "Fontconfig configuration files not found - weasyprint will likely throw warnings and use default fonts!"
    )
