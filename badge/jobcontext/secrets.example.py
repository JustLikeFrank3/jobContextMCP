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
"""

WIFI_SSID = "your-network"
WIFI_PASSWORD = "your-password"

# Cloud tenant, or your desktop's LAN address while developing.
BASE_URL = "https://jobcontext.ai"

# Dashboard → API Keys → scope "Conference badge".
BADGE_TOKEN = "jcmcp_replace_me"
