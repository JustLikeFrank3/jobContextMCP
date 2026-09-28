"""jobcontext client for the badge.

Talks to the badge-scoped surface only (/api/badge/*).  The token it carries
is minted with scope="badge" in the dashboard, so even though it sits in
plain text in secrets.py on a filesystem anyone can mount, it can do exactly
three things: search, queue a generation, poll that generation.

Configuration lives in the badge's root secrets.py alongside the WiFi
credentials the firmware already reads (the deploy tooling never copies an
app-local secrets file, by design):

    JOBCONTEXT_URL = "https://jobcontext.ai"
    JOBCONTEXT_TOKEN = "jcmcp_..."

Blocking note: MicroPython's requests is synchronous, so each call freezes the
frame loop for its duration.  The app draws a status frame first and makes
the call on the following frame, and polls on an interval rather than every
frame, so the freeze reads as a deliberate pause instead of a hang.
"""

import json

try:
    import requests
except ImportError:  # older MicroPython builds
    import urequests as requests

import secrets

_TIMEOUT = 15


class ApiError(Exception):
    """Any non-2xx or transport failure, with a message short enough to draw."""


def base_url():
    return getattr(secrets, "JOBCONTEXT_URL", "") or getattr(secrets, "BASE_URL", "")


def token():
    return getattr(secrets, "JOBCONTEXT_TOKEN", "") or getattr(secrets, "BADGE_TOKEN", "")


def configured():
    """Name the first missing setting, or return "" when all are present."""
    if not getattr(secrets, "WIFI_SSID", ""):
        return "WIFI_SSID"
    if not base_url():
        return "JOBCONTEXT_URL"
    if not token():
        return "JOBCONTEXT_TOKEN"
    return ""


def wifi_ready():
    """Non-blocking: True once connected. Call it every frame until then.

    The firmware's wifi module reads WIFI_SSID/WIFI_PASSWORD from the root
    secrets.py and keeps connecting in the background between calls.
    """
    import wifi

    return bool(wifi.connect())


def _url(path):
    return base_url().rstrip("/") + path


def _headers():
    return {
        "Authorization": "Bearer " + token(),
        "Content-Type": "application/json",
    }


def _request(method, path, body=None):
    try:
        response = requests.request(
            method,
            _url(path),
            data=json.dumps(body) if body is not None else None,
            headers=_headers(),
            timeout=_TIMEOUT,
        )
    except Exception as exc:  # noqa: BLE001 — anything here is "no network"
        raise ApiError("network: " + str(exc)[:40])

    try:
        if response.status_code >= 400:
            # 403 is the one worth naming: it means the token is real but was
            # minted with the wrong scope, which is otherwise a baffling
            # failure to debug from a badge.
            if response.status_code == 403:
                raise ApiError("token is not badge-scoped")
            if response.status_code == 401:
                raise ApiError("token rejected - regenerate it")
            raise ApiError("server said " + str(response.status_code))
        return response.json()
    finally:
        # MicroPython does not close these for you, and leaked sockets are how
        # a long-running badge app dies twenty minutes into a conference.
        response.close()


def ping():
    return _request("GET", "/api/badge/ping")


def search(query, limit=6):
    return _request("GET", "/api/badge/search?q=" + _quote(query) + "&limit=" + str(limit))


def request_materials(job_id, material="resume"):
    return _request("POST", "/api/badge/materials", {"job_id": job_id, "material": material})


def poll(work_id):
    return _request("GET", "/api/badge/work/" + str(work_id))


_SAFE = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_.~"


def _quote(text):
    """Percent-encode a query string. MicroPython has no urllib.parse."""
    out = []
    for char in text:
        if char in _SAFE:
            out.append(char)
        elif char == " ":
            out.append("+")
        else:
            out.append("%%%02X" % ord(char))
    return "".join(out)
