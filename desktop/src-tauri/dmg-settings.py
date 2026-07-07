# dmgbuild settings for the jobContext installer dmg.
#
# Used by CI's "Sign app & package dmg" step (and locally):
#
#   dmgbuild -s desktop/src-tauri/dmg-settings.py \
#     -D app=<path/to/jobContext.app> "jobContext" <out.dmg>
#
# dmgbuild writes the .DS_Store directly (no Finder/AppleScript), so this
# works headless on CI runners. Layout coordinates are paired with the
# committed background art — regenerate it with
# packaging/dmg/generate_background.py if you move anything.
import os.path

# dmgbuild exec()s this file without __file__, so paths are relative to the
# repo root — run dmgbuild from there (CI and the docs above both do).
app = defines.get("app", "jobContext.app")  # noqa: F821 — injected by dmgbuild
appname = os.path.basename(app)
_here = "desktop/src-tauri"

format = "UDZO"
files = [app]
symlinks = {"Applications": "/Applications"}

badge_icon = os.path.join(_here, "icons", "icon.icns")
background = os.path.join(_here, "dmg-background.tiff")

window_rect = ((200, 140), (660, 400))
default_view = "icon-view"
show_status_bar = False
show_tab_view = False
show_toolbar = False
show_pathbar = False
show_sidebar = False

icon_size = 128
text_size = 13
icon_locations = {
    appname: (165, 200),
    "Applications": (495, 200),
}
