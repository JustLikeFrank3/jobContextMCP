"""Runtime hook: resolve WeasyPrint's native libs from the bundle on macOS.

WeasyPrint loads Pango/GObject/HarfBuzz/Fontconfig via cffi's dlopen, which
falls back to ctypes.util.find_library() when the plain name doesn't resolve.
On macOS neither route searches the PyInstaller bundle dir: DYLD_* env vars
are read by dyld at process launch (setting them from Python is a no-op for
the current process), and stock CPython's find_library only searches system
paths. Homebrew's patched CPython masks this by searching /opt/homebrew/lib —
which makes builds on dev machines *look* self-contained while actually
loading the machine's Homebrew libs.

This wrapper resolves a requested name to the *versioned* dylib inside the
bundle's weasyprint_libs/ dir (e.g. harfbuzz → libharfbuzz.0.dylib). That
dir holds one coherent build of the whole stack (see hook-weasyprint.py):
WeasyPrint's harfbuzz and harfbuzz-subset handles must be the same build —
pairing Homebrew's subset with Pillow's vendored harfbuzz across an
hb_face_t SIGBUSes — and versioned names keep Pango and WeasyPrint on one
image per library.
"""
import os
import re
import sys

if sys.platform == "darwin":
    import ctypes.util

    _bundle_dir = os.path.join(getattr(sys, "_MEIPASS", ""), "weasyprint_libs")
    _orig_find_library = ctypes.util.find_library

    def _bundled_candidates(name):
        """Bundled dylibs matching `name`, versioned names first.

        Accepts lib<name>.dylib and lib<name>.<digits/dots>.dylib so that
        'harfbuzz' matches libharfbuzz.0.dylib but not libharfbuzz-subset.*.
        """
        pattern = re.compile(
            r"^lib" + re.escape(name) + r"(\.[0-9.]+)?\.dylib$"
        )
        matches = [f for f in _bundle_files if pattern.match(f)]
        # Versioned (longer) names first — they're what dyld load commands use.
        return sorted(matches, key=len, reverse=True)

    try:
        _bundle_files = os.listdir(_bundle_dir) if _bundle_dir else []
    except OSError:
        _bundle_files = []

    def _find_library_bundled_first(name):
        if _bundle_files and name:
            for filename in _bundled_candidates(name):
                return os.path.join(_bundle_dir, filename)
        return _orig_find_library(name)

    ctypes.util.find_library = _find_library_bundled_first
