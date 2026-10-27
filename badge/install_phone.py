#!/usr/bin/env python3
"""Install the badge app with the phone keyboard switched on.

Same install as badge/install.py — same modules, same compile-then-copy, same
backup and restore — plus a generated ``features.py`` that turns on the web
form. Everything else is delegated, so there is one installer to maintain and
this file cannot drift away from it.

    python badge/install_phone.py            # phone keyboard ON
    python badge/install.py                  # phone keyboard OFF (fallback)

**badge/install.py is the way back.** It deletes any ``features.py`` it finds,
so the plain installer really is the buttons-only build rather than the same
build carrying a stale flag from a run of this script. That is the whole point
of keeping both: if the listening socket misbehaves on hardware, reinstall
with install.py and the badge is exactly as it was.

With this on, the badge opens a socket on port 80 once WiFi is up and shows
its address on the search screen. Point a phone browser at it, type, submit —
the search runs on the badge. The buttons keep working throughout; the phone
is an addition, not a replacement.

Anyone on the same network can type into the badge. On a personal hotspot
that is you and nobody else, which is the intended setup and already the
recommended network (conference WiFi puts a captive portal in front of the
API). On a shared network, a stranger can run searches against your pipeline
— they cannot read anything back, since the results render on the badge in
your hand, but do not switch this on at a conference and walk away.

Every flag badge/install.py understands works here too:

    python badge/install_phone.py --dry-run
    python badge/install_phone.py --remove gallery --no-eject
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import install  # noqa: E402  — after the path insert, by design

# Read by jobcontext.inputs.phone_keyboard_enabled(). secrets.py overrides it,
# for flipping the switch without a reinstall.
FEATURES = {"PHONE_KEYBOARD": True}


def main(argv: "list[str] | None" = None) -> int:
    return install.main(argv, features=FEATURES)


if __name__ == "__main__":
    sys.exit(main())
