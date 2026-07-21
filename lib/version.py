"""Single source of truth for the app version.

The desktop release workflow (.github/workflows/desktop-release.yml) stamps
__version__ from the desktop-v* tag before freezing, so /healthz, the API
docs, and the installers all agree. Dev builds keep the -dev suffix.
"""
__version__ = "1.3.1"
