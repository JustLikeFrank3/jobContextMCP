"""Desktop-side driver for bidirectional cloud sync.

Talks to the hosted product's /api/sync/* endpoints with a personal access
token (created in the cloud dashboard's API Keys tab), which the cloud
resolves to the owner's partition. One `run_sync()` pass:

  1. pull rows:  cloud journal since our cursor → apply locally
  2. push rows:  local journal since our cursor → cloud applies
  3. files:      manifest diff (lib.sync.plan_file_sync) → transfer both ways;
                 true conflicts keep the remote copy as a " (sync conflict…)"
                 sibling instead of overwriting local work

Cursors and the file baseline live in the local sync_meta table, a summary
of the last run in sync_meta['last_summary'] for the Settings UI. Sync is
deliberately conservative: any transport error aborts the pass with the
cursors untouched, so a retry just resumes.
"""
from __future__ import annotations

import base64
import datetime
import json
import logging
import os
from pathlib import Path

_LOG = logging.getLogger(__name__)

_CURSOR_PULLED = "cloud_last_pulled_id"
_CURSOR_PUSHED = "local_last_pushed_id"
_FILE_BASELINE = "file_sync_baseline"
_LAST_SUMMARY = "last_sync_summary"

CONFLICT_TAG = " (sync conflict from cloud)"


def sync_settings() -> dict:
    """Cloud sync configuration from the desktop config.json."""
    from lib.config import get_active_config

    cfg = get_active_config()
    return {
        "url": _normalize_url(str(cfg.get("cloud_sync_url", "") or "")),
        "pat": str(cfg.get("cloud_sync_pat", "") or ""),
        "auto": bool(cfg.get("cloud_sync_auto", True)),
    }


def _normalize_url(url: str) -> str:
    """Coerce user-entered sync URLs to something the ingress accepts.

    A bare host gets https://; plain http is upgraded to https except for
    loopback (dev/self-sync) — the hosted ingress 308-redirects http anyway.
    """
    url = url.strip().rstrip("/")
    if not url:
        return ""
    if "://" not in url:
        url = f"https://{url}"
    if url.startswith("http://") and not any(
        h in url for h in ("127.0.0.1", "localhost")
    ):
        url = "https://" + url[len("http://"):]
    return url


def is_configured() -> bool:
    s = sync_settings()
    return bool(s["url"] and s["pat"])


def _client(url: str, pat: str):
    import httpx

    return httpx.Client(
        base_url=url,
        headers={"Authorization": f"Bearer {pat}"},
        timeout=60.0,
        # Ingresses 308 http→https (and may redirect on host normalization);
        # httpx doesn't follow redirects by default and a POST would fail.
        follow_redirects=True,
    )


def _local_root() -> Path:
    from lib.app_dirs import desktop_data_dir

    return desktop_data_dir()


def run_sync() -> dict:
    """One full bidirectional pass. Returns a summary dict (also persisted)."""
    from lib.db import get_connection
    from lib.sync import (
        apply_changes, export_changes, file_manifest, get_cursor,
        plan_file_sync, set_cursor,
    )

    settings = sync_settings()
    if not (settings["url"] and settings["pat"]):
        return {"status": "unconfigured"}

    summary: dict = {"status": "ok", "started": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")}
    root = _local_root()
    # Crash recovery: a process killed mid-apply leaves sync_state.applying=1,
    # which silences every journal trigger. No apply can be in flight when a
    # pass starts, so reset unconditionally.
    with get_connection() as con:
        con.execute("UPDATE sync_state SET applying = 0 WHERE id = 1")
        con.commit()
    try:
        with _client(settings["url"], settings["pat"]) as http:
            # 1. pull rows (loop while the cloud batch is truncated)
            pulled = 0
            while True:
                with get_connection() as con:
                    since = get_cursor(con, _CURSOR_PULLED)
                resp = http.post("/api/sync/changes", json={"since_id": since})
                resp.raise_for_status()
                batch = resp.json()
                if batch["changes"]:
                    with get_connection() as con:
                        stats = apply_changes(con, batch["changes"])
                    pulled += stats["applied"]
                    summary.setdefault("pull_stats", []).append(stats)
                with get_connection() as con:
                    set_cursor(con, _CURSOR_PULLED, batch["last_id"])
                if not batch.get("truncated"):
                    break
            summary["rows_pulled"] = pulled

            # 2. push rows
            pushed = 0
            while True:
                with get_connection() as con:
                    since = get_cursor(con, _CURSOR_PUSHED)
                    batch = export_changes(con, since)
                if batch["changes"]:
                    resp = http.post("/api/sync/apply", json={"changes": batch["changes"]})
                    resp.raise_for_status()
                    pushed += resp.json().get("applied", 0)
                with get_connection() as con:
                    set_cursor(con, _CURSOR_PUSHED, batch["last_id"])
                if not batch.get("truncated"):
                    break
            summary["rows_pushed"] = pushed

            # 3. files
            local = file_manifest(root)
            resp = http.post("/api/sync/files/manifest", json={})
            resp.raise_for_status()
            remote = resp.json()["manifest"]
            with get_connection() as con:
                row = con.execute(
                    "SELECT value FROM sync_meta WHERE key = ?", (_FILE_BASELINE,)
                ).fetchone()
            baseline = json.loads(row[0]) if row else {}
            plan = plan_file_sync(local, remote, baseline)

            for rel in plan["pull"]:
                _pull_file(http, root, rel)
            for rel in plan["push"]:
                _push_file(http, root, rel, local[rel])
            for rel in plan["conflict"]:
                # Keep local work; land the cloud version alongside it.
                _pull_file(http, root, rel, conflict=True)
            summary["files"] = {k: len(v) for k, v in plan.items()}

            # New baseline = post-sync local state.
            baseline = file_manifest(root)
            # Conflict copies are local-only working files, not sync state.
            baseline = {k: v for k, v in baseline.items() if CONFLICT_TAG not in k}
            with get_connection() as con:
                con.execute(
                    "INSERT INTO sync_meta (key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (_FILE_BASELINE, json.dumps(baseline)),
                )
                con.commit()
    except Exception as exc:  # noqa: BLE001 — summary carries the failure to the UI
        _LOG.warning("sync failed: %s", exc)
        summary["status"] = "error"
        summary["error"] = str(exc)[:300]

    summary["finished"] = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    from lib.db import get_connection as _gc

    with _gc() as con:
        con.execute(
            "INSERT INTO sync_meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (_LAST_SUMMARY, json.dumps(summary)),
        )
        con.commit()
    return summary


def last_summary() -> "dict | None":
    from lib.db import get_connection

    with get_connection() as con:
        row = con.execute(
            "SELECT value FROM sync_meta WHERE key = ?", (_LAST_SUMMARY,)
        ).fetchone()
    return json.loads(row[0]) if row else None


def _conflict_name(rel: str) -> str:
    p = Path(rel)
    return str(p.with_name(f"{p.stem}{CONFLICT_TAG}{p.suffix}"))


def _pull_file(http, root: Path, rel: str, conflict: bool = False) -> None:
    resp = http.post("/api/sync/files/get", json={"rel": rel})
    resp.raise_for_status()
    data = resp.json()
    dest_rel = _conflict_name(rel) if conflict else rel
    target = (root / dest_rel).resolve()
    if root.resolve() not in target.parents:
        raise ValueError(f"unsafe sync path: {rel!r}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(base64.b64decode(data["content_b64"]))
    if data.get("mtime"):
        os.utime(target, (data["mtime"], data["mtime"]))


def _push_file(http, root: Path, rel: str, meta: dict) -> None:
    target = (root / rel).resolve()
    if root.resolve() not in target.parents:
        raise ValueError(f"unsafe sync path: {rel!r}")
    resp = http.post(
        "/api/sync/files/put",
        json={
            "rel": rel,
            "content_b64": base64.b64encode(target.read_bytes()).decode("ascii"),
            "mtime": meta.get("mtime", 0.0),
        },
    )
    resp.raise_for_status()
