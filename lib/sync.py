"""Bidirectional workspace sync engine (desktop ⇄ cloud).

Row sync
--------
A ``sync_log`` journal records every local write to the synced tables via
AFTER-triggers, so no application write path changes. Each entry carries the
row's *sync identity* — a JSON natural key — plus a UTC timestamp. Sync is a
cursor exchange: each side exports journal entries newer than the peer's
cursor (collapsed to the latest per row, with the current row snapshot
attached) and applies the peer's batch inside one transaction.

Two table classes:

- **upsert** tables (applications, job_queue, people, oura_readiness): identified
  by a natural key; conflicts resolve last-writer-wins by journal timestamp.
  Deletes travel as tombstone entries.
- **append** tables (interviews, application_events, rejections, health_log,
  linkedin_posts): rows are immutable observations; identity is the JSON of
  their identity columns and apply is insert-if-absent, so replays dedupe by
  construction. Deletes are not synced.

Applying remote changes must not journal as *local* changes (echo loop): the
apply transaction flips ``sync_state.applying`` which every trigger checks —
SQLite's single-writer model guarantees no interleaved user writes — and the
engine journals applied rows itself with ``origin='remote'`` so future LWW
comparisons see the remote timestamp.

Cross-replica FKs: integer ids never leave the machine. application_events
exports its parent application's natural key instead of application_id and
re-resolves it on apply (parents order before children in TABLE_SPECS).

The ``oid`` column (oura_readiness) is partition metadata, not data: stripped
on export, stamped with the local user's oid on apply.

File sync (workspace documents) lives in sync_files.py-style helpers below:
manifests of (relpath, size, sha256, mtime), newest-mtime-wins, and when both
sides changed since the recorded baseline the loser is kept as a
" (sync conflict …)" sibling rather than overwritten.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_LOG = logging.getLogger(__name__)

_TS_FMT = "%Y-%m-%dT%H:%M:%S.%fZ"


def _now_ts() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime(_TS_FMT)


@dataclass(frozen=True)
class TableSpec:
    name: str
    kind: str                       # "upsert" | "append"
    identity: tuple[str, ...]       # natural-key (upsert) / identity (append) columns
    exclude: tuple[str, ...] = ("id",)   # never exported (machine-local)
    parent: "dict | None" = None    # {"table","fk_col"} — FK remapped via parent identity
    oid_col: str = ""               # partition column: stripped/restamped


# Order matters: parents before children so FK remaps resolve within a batch.
TABLE_SPECS: tuple[TableSpec, ...] = (
    TableSpec("applications", "upsert", ("company", "role")),
    TableSpec("job_queue", "upsert", ("company", "role")),
    TableSpec("people", "upsert", ("name",)),
    TableSpec("oura_readiness", "upsert", ("date",), exclude=("id", "oid"), oid_col="oid"),
    TableSpec("interviews", "append", ("timestamp", "company", "role")),
    TableSpec(
        "application_events", "append", ("type", "date", "notes"),
        parent={"table": "applications", "fk_col": "application_id"},
        exclude=("id", "application_id"),
    ),
    TableSpec("rejections", "append", ("company", "role", "logged_at")),
    TableSpec("health_log", "append", ("timestamp", "date")),
    TableSpec("linkedin_posts", "append", ("timestamp", "posted_date", "title")),
)

_SPECS_BY_NAME = {s.name: s for s in TABLE_SPECS}


# ── schema (idempotent — invoked from lib.db migrations) ──────────────────────

def ensure_sync_schema(con) -> None:
    """Create the journal, state flag, cursor store, and per-table triggers."""
    con.execute(
        """CREATE TABLE IF NOT EXISTS sync_log (
            id     INTEGER PRIMARY KEY AUTOINCREMENT,
            tbl    TEXT NOT NULL,
            op     TEXT NOT NULL,          -- upsert | insert | delete
            nk     TEXT NOT NULL,          -- JSON array of identity values
            ts     TEXT NOT NULL,          -- UTC ISO
            origin TEXT NOT NULL DEFAULT 'local'
        )"""
    )
    con.execute("CREATE INDEX IF NOT EXISTS idx_sync_log_tbl_nk ON sync_log (tbl, nk, id)")
    con.execute("CREATE TABLE IF NOT EXISTS sync_state (id INTEGER PRIMARY KEY CHECK (id = 1), applying INTEGER NOT NULL DEFAULT 0)")
    con.execute("INSERT OR IGNORE INTO sync_state (id, applying) VALUES (1, 0)")
    con.execute("CREATE TABLE IF NOT EXISTS sync_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")

    existing = {
        r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    for spec in TABLE_SPECS:
        if spec.name not in existing:
            continue  # table not present in this deployment's schema yet
        nk_new = "json_array(" + ", ".join(f"NEW.{c}" for c in spec.identity) + ")"
        nk_old = "json_array(" + ", ".join(f"OLD.{c}" for c in spec.identity) + ")"
        guard = "(SELECT applying FROM sync_state WHERE id = 1) = 0"
        ts = "strftime('%Y-%m-%dT%H:%M:%fZ','now')"
        if spec.kind == "upsert":
            ops = [("ins", "INSERT", "upsert", nk_new), ("upd", "UPDATE", "upsert", nk_new), ("del", "DELETE", "delete", nk_old)]
        else:
            ops = [("ins", "INSERT", "insert", nk_new)]
        for tag, event, op, nk_expr in ops:
            con.execute(
                f"""CREATE TRIGGER IF NOT EXISTS trg_sync_{spec.name}_{tag}
                    AFTER {event} ON {spec.name}
                    WHEN {guard}
                    BEGIN
                        INSERT INTO sync_log (tbl, op, nk, ts, origin)
                        VALUES ('{spec.name}', '{op}', {nk_expr}, {ts}, 'local');
                    END"""
            )


# ── helpers ────────────────────────────────────────────────────────────────────

def _columns(con, table: str) -> list[str]:
    return [r[1] for r in con.execute(f"PRAGMA table_info({table})").fetchall()]


def _row_payload(con, spec: TableSpec, nk_values: list) -> "dict | None":
    where = " AND ".join(f"{c} IS ?" for c in spec.identity)
    row = con.execute(
        f"SELECT * FROM {spec.name} WHERE {where} ORDER BY id DESC LIMIT 1", nk_values
    ).fetchone()
    if row is None:
        return None
    payload = {k: row[k] for k in row.keys() if k not in spec.exclude}
    if spec.parent:
        parent_spec = _SPECS_BY_NAME[spec.parent["table"]]
        fk = row[spec.parent["fk_col"]]
        parent_nk = None
        if fk is not None:
            prow = con.execute(
                f"SELECT * FROM {parent_spec.name} WHERE id = ?", (fk,)
            ).fetchone()
            if prow is not None:
                parent_nk = [prow[c] for c in parent_spec.identity]
        payload["__parent_nk__"] = parent_nk
    return payload


def _local_latest_ts(con, tbl: str, nk: str) -> "str | None":
    row = con.execute(
        "SELECT ts FROM sync_log WHERE tbl = ? AND nk = ? ORDER BY id DESC LIMIT 1",
        (tbl, nk),
    ).fetchone()
    return row[0] if row else None


# ── export ─────────────────────────────────────────────────────────────────────

def export_changes(con, since_id: int, limit: int = 500) -> dict:
    """Local journal entries after ``since_id``, newest-per-row, with snapshots."""
    rows = con.execute(
        "SELECT id, tbl, op, nk, ts FROM sync_log WHERE id > ? AND origin = 'local' ORDER BY id",
        (since_id,),
    ).fetchall()
    latest: dict[tuple[str, str], Any] = {}
    last_id = since_id
    for r in rows[:limit]:
        latest[(r["tbl"], r["nk"])] = r
        last_id = r["id"]
    truncated = len(rows) > limit

    changes = []
    for (tbl, nk), r in sorted(latest.items(), key=lambda kv: kv[1]["id"]):
        spec = _SPECS_BY_NAME.get(tbl)
        if spec is None:
            continue
        nk_values = json.loads(nk)
        payload = None
        op = r["op"]
        if op in ("upsert", "insert"):
            payload = _row_payload(con, spec, nk_values)
            if payload is None and spec.kind == "upsert":
                op = "delete"  # row vanished after journaling
            elif payload is None:
                continue
        changes.append({"tbl": tbl, "op": op, "nk": nk, "ts": r["ts"], "row": payload})
    return {"last_id": last_id, "truncated": truncated, "changes": changes}


# ── apply ──────────────────────────────────────────────────────────────────────

@dataclass
class ApplyStats:
    applied: int = 0
    skipped_lww: int = 0
    skipped_dupe: int = 0
    skipped_missing_parent: int = 0
    errors: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "applied": self.applied,
            "skipped_lww": self.skipped_lww,
            "skipped_dupe": self.skipped_dupe,
            "skipped_missing_parent": self.skipped_missing_parent,
            "errors": self.errors[:10],
        }


def _current_oid() -> str:
    from lib.user_context import get_current_user_oid

    return get_current_user_oid() or ""


def apply_changes(con, changes: list[dict]) -> dict:
    """Apply a peer's change batch inside one transaction (LWW, dedupe, remap)."""
    stats = ApplyStats()
    order = {s.name: i for i, s in enumerate(TABLE_SPECS)}
    batch = sorted(
        (c for c in changes if c.get("tbl") in _SPECS_BY_NAME),
        key=lambda c: (order[c["tbl"]], c.get("ts") or ""),
    )
    con.execute("UPDATE sync_state SET applying = 1 WHERE id = 1")
    try:
        for change in batch:
            try:
                _apply_one(con, change, stats)
            except Exception as exc:  # noqa: BLE001 — one bad row must not sink the batch
                stats.errors.append(f"{change.get('tbl')}/{change.get('nk')}: {exc}")
        con.commit()
    finally:
        con.execute("UPDATE sync_state SET applying = 0 WHERE id = 1")
        con.commit()
    return stats.as_dict()


def _apply_one(con, change: dict, stats: ApplyStats) -> None:
    spec = _SPECS_BY_NAME[change["tbl"]]
    nk, ts, op = change["nk"], change.get("ts") or _now_ts(), change["op"]
    nk_values = json.loads(nk)
    where = " AND ".join(f"{c} IS ?" for c in spec.identity)

    if spec.kind == "append":
        exists = con.execute(
            f"SELECT 1 FROM {spec.name} WHERE {where} LIMIT 1", nk_values
        ).fetchone()
        if exists:
            stats.skipped_dupe += 1
            return
    else:
        local_ts = _local_latest_ts(con, spec.name, nk)
        if local_ts is not None and local_ts >= ts:
            stats.skipped_lww += 1
            return

    if op == "delete":
        con.execute(f"DELETE FROM {spec.name} WHERE {where}", nk_values)
    else:
        row = dict(change.get("row") or {})
        parent_nk = row.pop("__parent_nk__", None)
        if spec.parent:
            fk_val = None
            if parent_nk:
                parent_spec = _SPECS_BY_NAME[spec.parent["table"]]
                pwhere = " AND ".join(f"{c} IS ?" for c in parent_spec.identity)
                prow = con.execute(
                    f"SELECT id FROM {parent_spec.name} WHERE {pwhere} ORDER BY id DESC LIMIT 1",
                    parent_nk,
                ).fetchone()
                if prow is None:
                    stats.skipped_missing_parent += 1
                    return
                fk_val = prow[0]
            row[spec.parent["fk_col"]] = fk_val
        if spec.oid_col:
            row[spec.oid_col] = _current_oid()
        valid = set(_columns(con, spec.name))
        row = {k: v for k, v in row.items() if k in valid}
        if spec.kind == "upsert":
            con.execute(f"DELETE FROM {spec.name} WHERE {where}", nk_values)
        cols = ", ".join(row.keys())
        marks = ", ".join("?" for _ in row)
        con.execute(f"INSERT INTO {spec.name} ({cols}) VALUES ({marks})", list(row.values()))

    con.execute(
        "INSERT INTO sync_log (tbl, op, nk, ts, origin) VALUES (?, ?, ?, ?, 'remote')",
        (spec.name, op, nk, ts),
    )
    stats.applied += 1


# ── cursors ────────────────────────────────────────────────────────────────────

def get_cursor(con, key: str) -> int:
    row = con.execute("SELECT value FROM sync_meta WHERE key = ?", (key,)).fetchone()
    return int(row[0]) if row else 0


def set_cursor(con, key: str, value: int) -> None:
    con.execute(
        "INSERT INTO sync_meta (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, str(value)),
    )
    con.commit()


# ── workspace file sync ────────────────────────────────────────────────────────

# Everything document-like syncs; databases, config, backups, and index
# artifacts stay machine-local.
_FILE_EXCLUDE_PARTS = ("db",)
_FILE_EXCLUDE_NAMES = ("config.json", ".DS_Store")
_FILE_EXCLUDE_SUFFIXES = (".bak", ".faiss", ".pkl")


def _file_synced(rel: Path) -> bool:
    if rel.parts and rel.parts[0] in _FILE_EXCLUDE_PARTS:
        return False
    if rel.name in _FILE_EXCLUDE_NAMES or rel.name.startswith("."):
        return False
    return rel.suffix.lower() not in _FILE_EXCLUDE_SUFFIXES


def file_manifest(root: Path) -> dict[str, dict]:
    """{relpath: {size, mtime, sha256}} for every synced file under root."""
    manifest: dict[str, dict] = {}
    root = root.resolve()
    if not root.is_dir():
        return manifest
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if not _file_synced(rel):
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        stat = path.stat()
        manifest[str(rel)] = {"size": stat.st_size, "mtime": stat.st_mtime, "sha256": digest}
    return manifest


def plan_file_sync(local: dict, remote: dict, baseline: dict) -> dict:
    """Decide per-file direction: pull, push, conflict, or nothing.

    baseline = the manifest agreed at last sync (sha only). A file changed on
    one side syncs to the other; changed on both sides (vs baseline) is a
    conflict — the puller keeps its copy under a conflict name.
    """
    pulls, pushes, conflicts = [], [], []
    for rel in sorted(set(local) | set(remote)):
        l, r = local.get(rel), remote.get(rel)
        base_sha = (baseline.get(rel) or {}).get("sha256")
        if l and r:
            if l["sha256"] == r["sha256"]:
                continue
            l_changed = l["sha256"] != base_sha
            r_changed = r["sha256"] != base_sha
            if l_changed and r_changed:
                conflicts.append(rel)
            elif r_changed:
                pulls.append(rel)
            else:
                pushes.append(rel)
        elif r and not l:
            if base_sha and base_sha == r["sha256"]:
                continue  # existed at baseline, locally deleted → leave deleted
            pulls.append(rel)
        elif l and not r:
            if base_sha and base_sha == l["sha256"]:
                continue  # remotely deleted → leave deleted
            pushes.append(rel)
    return {"pull": pulls, "push": pushes, "conflict": conflicts}
