"""Copy to secrets.py on the badge and fill in. secrets.py is gitignored.

Everything in this file ends up in plain text on the badge's filesystem, which
anyone can mount by double-tapping reset and plugging in a USB-C cable. Treat
it as public:

  * BADGE_TOKEN must be minted with scope "badge" (Dashboard → API Keys →
    "Conference badge"). A badge-scoped key can search, queue a generation,
    and poll it — nothing else. A full-scope key on this device would hand
    over your whole job search to whoever picks it up.
  * Use a guest/hotspot WiFi network if you can. These credentials are as
    readable as the token.
  * TLS is unverified on this MicroPython build (no CERT_REQUIRED), so the
    token is liftable on hostile WiFi. Badge-scoped, so bounded, but revoke
    it after an event.
"""

# Every network the badge may use, tried in this order when in range. Phone
# hotspots: the badge is 2.4 GHz only (iPhone: Personal Hotspot -> "Maximize
# Compatibility" ON), and copy the name exactly — iPhone hotspot names use a
# curly apostrophe (Frank’s iPhone), not a straight one.
WIFI_NETWORKS = [
    ("your-home-network", "your-password"),
    ("Your’s iPhone", "hotspot-password"),
]

# Cloud tenant, or your desktop's LAN address while developing.
BASE_URL = "https://jobcontext.ai"

# Dashboard → API Keys → scope "Conference badge".
BADGE_TOKEN = "jcmcp_replace_me"

# Optional. A wired keyboard on the qwiic port (M5Stack CardKB / CardKB2) is
# found by scanning, so normally you set nothing here: 0x5F is the CardKB
# family's documented address, and a lone unknown device on an otherwise empty
# bus is taken to be the thing you just plugged in. Set this only when the bus
# has several devices and none of them is 0x5F — the scan declines to guess
# which stranger is the keyboard rather than send keystroke reads to a sensor.
# badge/probe.py prints what is actually on the bus.
# KEYBOARD_I2C_ADDR = 0x5F
