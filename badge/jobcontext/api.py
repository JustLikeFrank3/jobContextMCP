"""jobcontext client for the badge.

Talks to the badge-scoped surface only (/api/badge/*).  The token it carries
is minted with scope="badge" in the dashboard, so even though it sits in
plain text in secrets.py on a filesystem anyone can mount, it can only search
(your pipeline, or open roles on the web), add a found role to the pipeline,
queue a resume/cover letter, and poll that generation.

Blocking note: MicroPython's requests is synchronous, so each call freezes the
frame loop for its duration.  The app draws a "working" frame *before*
calling, and polls on an interval rather than every frame, so the freeze is
visible as a deliberate pause instead of a hang.
"""

import json

try:
    import requests
except ImportError:  # older MicroPython builds
    import urequests as requests

import network
import time

try:
    from . import secrets
except ImportError:
    try:
        import secrets
    except ImportError:  # installed without one — say so on screen, don't crash
        secrets = None

_TIMEOUT = 15


class ApiError(Exception):
    """Any non-2xx or transport failure, with a message short enough to draw."""


def connect_wifi(status=None):
    """Bring up WiFi, returning True once connected.

    *status* is an optional callable used to report progress on screen — the
    badge otherwise looks frozen for the ten seconds a DHCP lease can take.
    """
    if secrets is None:
        raise ApiError("no secrets.py - copy secrets.example.py and fill it in")
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if wlan.isconnected():
        return True
    wlan.connect(secrets.WIFI_SSID, secrets.WIFI_PASSWORD)
    for attempt in range(40):  # ~20s
        if wlan.isconnected():
            return True
        if status:
            status("connecting to wifi" + "." * (attempt % 4))
        time.sleep(0.5)
    return False


def _url(path):
    return secrets.BASE_URL.rstrip("/") + path


def _headers():
    return {
        "Authorization": "Bearer " + secrets.BADGE_TOKEN,
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
            raise ApiError(_detail(response) or "server said " + str(response.status_code))
        return response.json()
    finally:
        # MicroPython does not close these for you, and leaked sockets are how
        # a long-running badge app dies twenty minutes into a conference.
        response.close()


def _detail(response):
    """The server's own one-line reason (FastAPI's "detail"), if it sent one."""
    try:
        detail = response.json().get("detail")
    except Exception:  # noqa: BLE001 — non-JSON error body
        return ""
    return detail if isinstance(detail, str) else ""


def ping():
    return _request("GET", "/api/badge/ping")


def search(query, limit=6):
    return _request("GET", "/api/badge/search?q=" + _quote(query) + "&limit=" + str(limit))


def jobs(query, limit=6):
    """Open roles on the web (not the pipeline). Returns search_id + results."""
    return _request("GET", "/api/badge/jobs?q=" + _quote(query) + "&limit=" + str(limit))


def queue_job(search_id, number):
    """Add web result *number* to the pipeline; returns its job_id."""
    return _request("POST", "/api/badge/jobs/queue", {"search_id": search_id, "number": number})


def request_materials(job_id, material="resume"):
    return _request("POST", "/api/badge/materials", {"job_id": job_id, "material": material})


def poll(work_id):
    return _request("GET", "/api/badge/work/" + str(work_id))


_SAFE = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_.~"


def _quote(text):
    """Percent-encode a query string. MicroPython has no urllib.parse."""
    out = []
    for byte in text.encode("utf-8"):
        char = chr(byte)
        if char in _SAFE:
            out.append(char)
        elif char == " ":
            out.append("+")
        else:
            out.append("%%%02X" % byte)
    return "".join(out)
