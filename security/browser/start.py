"""Real app, disposable browser-test data, no inherited credentials or egress.

Only the browser smoke runner calls this helper. It never accepts a target URL.
The socket guard is test-only and deliberately stays outside production code.
"""
from __future__ import annotations

import ipaddress
import json
import os
from pathlib import Path
import socket
import sys


def is_loopback(host):
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def block_external_connections():
    connect = socket.socket.connect
    connect_ex = socket.socket.connect_ex
    getaddrinfo = socket.getaddrinfo

    def checked_address(sock, address):
        if sock.family in (socket.AF_INET, socket.AF_INET6) and not is_loopback(address[0]):
            raise OSError("Browser fixture blocks all non-loopback connections")

    def safe_connect(sock, address):
        checked_address(sock, address)
        return connect(sock, address)

    def safe_connect_ex(sock, address):
        checked_address(sock, address)
        return connect_ex(sock, address)

    def safe_getaddrinfo(host, *args, **kwargs):
        if host is not None and not is_loopback(host):
            raise OSError("Browser fixture blocks external DNS resolution")
        return getaddrinfo(host, *args, **kwargs)

    socket.socket.connect = safe_connect
    socket.socket.connect_ex = safe_connect_ex
    socket.getaddrinfo = safe_getaddrinfo


def main():
    root = Path(sys.argv[1]).resolve()
    port = int(sys.argv[2])
    if not root.is_dir() or not 1024 <= port <= 65535:
        raise SystemExit("Expected a fresh temporary fixture directory and local port")
    for name in ("data", "resumes", "leetcode"):
        (root / name).mkdir()
    materials = root / "resumes" / "07-Job-Assessments"
    materials.mkdir()
    (materials / "security-preview.md").write_text(
        "# Browser security fixture\n\n**Synthetic** assessment.\n\n"
        "<script>window.fixtureInjected = true</script>\n",
        encoding="utf-8",
    )
    (materials / "security-preview.txt").write_text("Synthetic raw preview\n", encoding="utf-8")
    (materials / "security-fallback.md").write_text("Synthetic fallback preview\n", encoding="utf-8")
    config = root / "config.json"
    config.write_text(json.dumps({
        "data_folder": str(root / "data"),
        "resume_folder": str(root / "resumes"),
        "leetcode_folder": str(root / "leetcode"),
        "side_project_folders": [],
    }), encoding="utf-8")
    # Explicit whitelist: no inherited cloud/auth/LLM/proxy/tenant settings.
    path = os.environ.get("PATH", "")
    os.environ.clear()
    os.environ.update({
        "PATH": path, "HOME": str(root), "LANG": "C.UTF-8",
        "PYTHONUNBUFFERED": "1", "PYTHONDONTWRITEBYTECODE": "1",
        "JOBCONTEXT_CONFIG": str(config), "HOST": "127.0.0.1", "PORT": str(port),
        "API_KEY": "browser-synthetic-not-a-secret", "ENABLE_REMOTE": "false",
    })
    block_external_connections()
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    import uvicorn
    from transport.http.main import app
    from lib.db import get_connection
    from lib import work

    # Conference smoke uses real authenticated routes and dispatcher, but only
    # synthetic data and an offline executor. Never call a paid search or LLM.
    with get_connection() as con:
        con.execute("INSERT INTO job_queue (company, role, jd, status) VALUES (?, ?, ?, ?)",
                    ("Conference Fixture", "Platform Engineer", "Synthetic job description", "pending"))
    work.register_kind("badge_materials", lambda inputs: {
        "company": "Conference Fixture", "resume": "Synthetic resume", "cover_letter": "Synthetic letter",
    })

    # uvloop performs native socket I/O and bypasses the Python socket guard.
    # This fixture must use asyncio's guarded Python sockets, independently of
    # production's auto-selected event loop.
    uvicorn.run(
        app, host="127.0.0.1", port=port,
        loop="asyncio", reload=False, log_level="info",
    )


if __name__ == "__main__":
    main()
