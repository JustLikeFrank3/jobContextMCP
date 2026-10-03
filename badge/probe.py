"""Hardware probe — run this on the badge FIRST, before the app.

Why this exists: `ui.py` guesses at the firmware's drawing API, the font's
character width, and the button objects, because all three differ between
Pimoroni's e-ink Badger builds and the Tufty 2350 colour build and none of
them can be verified from a laptop. This script asks the badge directly and
prints an answer you can paste back, so ui.py gets corrected from fact
rather than from a second guess.

It writes nothing, connects to nothing, and needs no secrets.py.

Usage
-----
1. Double-tap reset to mount the badge as a USB drive.
2. Copy this file to the root of that drive.
3. Open a REPL (Thonny, mpremote, screen) and run:

       import probe

   Or from the badge's file browser, run probe.py directly.
4. Paste the whole output back.

If an individual check explodes, it prints the exception and carries on —
a probe that dies on its first surprise tells you the least.
"""


def _hr(title):
    print("\n--- " + title + " " + "-" * max(0, 40 - len(title)))


def _try(label, fn):
    """Run fn(), printing either its value or the exception it raised."""
    try:
        print("  %-26s %r" % (label, fn()))
    except Exception as exc:  # noqa: BLE001 — the failure IS the datum
        print("  %-26s !! %s: %s" % (label, type(exc).__name__, exc))


def platform_info():
    _hr("platform")
    import sys

    _try("sys.implementation", lambda: sys.implementation)
    _try("sys.version", lambda: sys.version)
    _try("sys.platform", lambda: sys.platform)
    _try("sys.path", lambda: sys.path)

    import gc

    gc.collect()
    _try("gc.mem_free()", gc.mem_free)
    _try("gc.mem_alloc()", gc.mem_alloc)

    try:
        import machine

        _try("machine.freq()", machine.freq)
        _try("unique_id", lambda: machine.unique_id())
    except ImportError as exc:
        print("  machine                    !! %s" % exc)


def module_scan():
    """Which candidate firmware modules exist, and what do they export?

    ui.py tries `badgeware` first, then a PicoGraphics/pimoroni pair. This
    says which of those is real — and if neither, what the badge calls it.
    """
    _hr("firmware modules")
    candidates = (
        "badgeware", "picographics", "pimoroni", "tufty", "tufty2350",
        "badger2040", "badger_os", "monaos", "mona", "jpegdec", "pngdec",
        "network", "bluetooth", "aioble", "requests", "urequests",
        "ssl", "tls", "machine", "gc",
    )
    for name in candidates:
        try:
            mod = __import__(name)
        except Exception as exc:  # noqa: BLE001
            print("  %-14s absent (%s)" % (name, type(exc).__name__))
            continue
        exports = [a for a in dir(mod) if not a.startswith("_")]
        print("  %-14s PRESENT (%d exports)" % (name, len(exports)))
        print("                 %s" % (exports[:24],))

    _hr("built-in module list")
    try:
        help("modules")
    except Exception as exc:  # noqa: BLE001
        print("  help('modules') failed: %s" % exc)


def display_api():
    """Find the display object and learn which drawing methods it really has.

    ui.py calls set_pen/create_pen/clear/text/rectangle/update. If the real
    object names them differently, this is where that shows up.
    """
    _hr("display object")
    display = None
    source = ""

    try:
        import badgeware

        display = getattr(badgeware, "display", None)
        source = "badgeware.display"
        print("  badgeware exports: %s" % [a for a in dir(badgeware) if not a.startswith("_")])
    except ImportError:
        pass

    if display is None:
        try:
            import picographics

            consts = [a for a in dir(picographics) if a.startswith("DISPLAY")]
            print("  picographics DISPLAY_* constants:")
            print("    %s" % consts)
            print("  (not instantiating — pick the Tufty constant and retry by hand)")
            source = "picographics (uninstantiated)"
        except ImportError:
            print("  neither badgeware nor picographics imported")

    if display is not None:
        print("  found via %s -> %r" % (source, display))
        methods = [a for a in dir(display) if not a.startswith("_")]
        print("  methods: %s" % methods)
        for need in ("set_pen", "create_pen", "clear", "text", "rectangle",
                     "update", "measure_text", "set_font", "get_bounds"):
            print("    %-14s %s" % (need, "YES" if hasattr(display, need) else "no"))

        # Font width is what every truncation width in ui.py is derived from.
        if hasattr(display, "measure_text"):
            _hr("font metrics (THE important numbers)")
            for scale in (1, 2, 3):
                _try(
                    "measure 'M'x10 scale=%d" % scale,
                    lambda s=scale: display.measure_text("M" * 10, s),
                )
                _try(
                    "measure 'i'x10 scale=%d" % scale,
                    lambda s=scale: display.measure_text("i" * 10, s),
                )
        if hasattr(display, "get_bounds"):
            _try("get_bounds()", display.get_bounds)


def buttons():
    """Report how buttons are exposed, and which are currently held.

    Hold UP while running this to confirm the mapping is live rather than
    just present.
    """
    _hr("buttons")
    try:
        import badgeware

        found = [a for a in dir(badgeware) if "button" in a.lower() or a in ("UP", "DOWN", "A", "B", "C")]
        print("  badgeware button-ish exports: %s" % found)
        for name in found:
            obj = getattr(badgeware, name, None)
            kind = type(obj).__name__
            state = "?"
            for meth in ("read", "value", "is_pressed"):
                if hasattr(obj, meth):
                    try:
                        state = "%s()=%r" % (meth, getattr(obj, meth)())
                    except Exception as exc:  # noqa: BLE001
                        state = "%s() raised %s" % (meth, type(exc).__name__)
                    break
            print("    %-18s %-12s %s" % (name, kind, state))
        return
    except ImportError:
        pass

    try:
        from pimoroni import Button  # noqa: F401

        print("  pimoroni.Button available — ui.py's fallback path applies.")
        print("  Pin numbers must be confirmed against the Tufty schematic;")
        print("  ui.py currently guesses UP=22 DOWN=6 A=7 B=8 C=9.")
    except ImportError:
        print("  no pimoroni.Button either — report what the badge's own")
        print("  preloaded apps import for buttons.")


def net_and_tls():
    """Can the badge do HTTPS at all, and does it verify certificates?

    api.py talks to jobcontext over TLS. MicroPython builds vary in whether
    cert verification is even available, which decides how much the badge
    token is worth protecting in transit.
    """
    _hr("network / TLS capability")
    try:
        import network

        print("  network exports: %s" % [a for a in dir(network) if not a.startswith("_")])
        wlan = network.WLAN(network.STA_IF)
        _try("wlan.active()", wlan.active)
        _try("wlan.isconnected()", wlan.isconnected)
        print("  (not connecting — no secrets.py needed for this probe)")
    except Exception as exc:  # noqa: BLE001
        print("  network unavailable: %s" % exc)

    for name in ("ssl", "tls"):
        try:
            mod = __import__(name)
            print("  %s exports: %s" % (name, [a for a in dir(mod) if not a.startswith("_")]))
            print("    CERT_REQUIRED present: %s" % hasattr(mod, "CERT_REQUIRED"))
        except ImportError:
            print("  %s absent" % name)

    for name in ("requests", "urequests"):
        try:
            mod = __import__(name)
            print("  %s present; request() signature-ish: %s"
                  % (name, [a for a in dir(mod) if not a.startswith("_")]))
        except ImportError:
            print("  %s absent" % name)


def ble_host_capability():
    """Is a BLE keyboard even reachable on this firmware?

    The badge app's Bluetooth-keyboard path needs HID-over-GATT *host*
    support, which needs pairing/bonding compiled in. These two attributes
    are the cheapest way to find out whether that is worth attempting at
    all: no gap_pair means no encrypted link, and no encrypted link means
    no keyboard will send reports.
    """
    _hr("BLE host capability")
    try:
        import bluetooth
    except ImportError as exc:
        print("  bluetooth module absent (%s) — BLE keyboard is a dead end" % exc)
        return
    exports = [a for a in dir(bluetooth) if not a.startswith("_")]
    print("  bluetooth exports: %s" % exports)
    try:
        ble = bluetooth.BLE()
        for attr in ("gap_pair", "gap_passkey", "gap_connect", "gatt_client",
                     "gattc_discover_services", "irq", "config"):
            print("    %-24s %s" % (attr, "YES" if hasattr(ble, attr) else "no"))
        print("  gap_pair present => pairing/bonding compiled in => HOGP host")
        print("  is at least attemptable. Absent => stop; use the buttons.")
    except Exception as exc:  # noqa: BLE001
        print("  BLE() construction failed: %s: %s" % (type(exc).__name__, exc))


def run():
    print("=" * 52)
    print(" jobcontext badge probe")
    print("=" * 52)
    for step in (platform_info, module_scan, display_api, buttons,
                 net_and_tls, ble_host_capability):
        try:
            step()
        except Exception as exc:  # noqa: BLE001 — never let one check end the run
            print("\n!! %s blew up: %s: %s" % (step.__name__, type(exc).__name__, exc))
    print("\n" + "=" * 52)
    print(" probe complete — paste everything above")
    print("=" * 52)


run()
