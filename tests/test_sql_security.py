"""Adversarial evidence for the narrowly scoped B608 SQL dispositions.

Every database is synthetic and in-memory. These tests exercise the public sync
entry points: a peer controls table labels, row keys, row values, and natural
keys, but must never turn those into SQL identifiers or SQL syntax.
"""
import json
import re
import sqlite3

import pytest

from lib import db, io_sqlite, sync
from tools import certification


_ATTACK = "x'); DELETE FROM people; --"
_FUTURE = "9999-01-01T00:00:00.000000Z"


def _connection(*, with_sync=True):
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript("""
        CREATE TABLE people (id INTEGER PRIMARY KEY, name TEXT, notes TEXT);
        CREATE TABLE applications (id INTEGER PRIMARY KEY, company TEXT, role TEXT);
        CREATE TABLE application_events (
            id INTEGER PRIMARY KEY, application_id INTEGER, type TEXT, date TEXT, notes TEXT
        );
        CREATE TABLE stories (id INTEGER PRIMARY KEY, timestamp TEXT, title TEXT);
        CREATE TABLE star_stories (id TEXT PRIMARY KEY, title TEXT);
    """)
    # Use the application's actual fixed employer schema, not a permissive mock.
    employer_ddl = next(sql for sql in db._MIGRATIONS
                        if sql.startswith("CREATE TABLE IF NOT EXISTS employer_directory"))
    con.execute(employer_ddl)
    if with_sync:
        sync.ensure_sync_schema(con)
    return con


@pytest.fixture()
def con():
    connection = _connection()
    try:
        yield connection
    finally:
        connection.close()


def _change(table="people", *, nk=None, row=None, op="upsert", ts=_FUTURE):
    return {"tbl": table, "op": op, "nk": json.dumps(nk or [_ATTACK]),
            "row": row, "ts": ts}


def test_registry_identifiers_are_fixed_simple_sql_names():
    """Schema/spec edits must preserve the invariant behind B608 exceptions."""
    assert len(sync._SPECS_BY_NAME) == len(sync.TABLE_SPECS)
    for spec in sync.TABLE_SPECS:
        names = [spec.name, *spec.identity, *spec.exclude]
        if spec.oid_col:
            names.append(spec.oid_col)
        if spec.parent:
            assert spec.parent["table"] in sync._SPECS_BY_NAME
            names.extend(spec.parent.values())
        assert all(re.fullmatch(r"[a-z_][a-z_0-9]*", name) for name in names)
        assert spec.kind in {"upsert", "append"}


@pytest.mark.parametrize("table", ["people; DROP TABLE people; --", "sync_meta", "sqlite_master"])
def test_unknown_peer_table_is_not_executed(con, table):
    con.execute("INSERT INTO people (name) VALUES ('untouched')")
    stats = sync.apply_changes(con, [_change(table, row={"name": _ATTACK})])
    assert stats["applied"] == 0
    assert stats["errors"] == []
    assert [r[0] for r in con.execute("SELECT name FROM people")] == ["untouched"]


def test_peer_column_keys_are_allowlisted_and_values_remain_data(con):
    con.execute("INSERT INTO people (name, notes) VALUES ('untouched', 'keep')")
    stats = sync.apply_changes(con, [_change(row={
        "name": _ATTACK, "notes": _ATTACK,
        "name) VALUES ('injected'); DELETE FROM people; --": "bad",
        "unexpected_column": "bad",
    })])
    assert stats["errors"] == []
    assert stats["applied"] == 1
    assert [tuple(r) for r in con.execute("SELECT name, notes FROM people ORDER BY id")] == [
        ("untouched", "keep"), (_ATTACK, _ATTACK),
    ]
    # Natural keys bind in both the upsert DELETE and explicit tombstone DELETE.
    newer = _FUTURE.replace("01-01", "01-02")
    stats = sync.apply_changes(con, [_change(op="delete", ts=newer)])
    assert stats["applied"] == 1
    assert [r[0] for r in con.execute("SELECT name FROM people")] == ["untouched"]


def test_export_trigger_and_snapshot_bind_hostile_natural_keys(con):
    con.execute("INSERT INTO people (name, notes) VALUES (?, ?)", (_ATTACK, _ATTACK))
    batch = sync.export_changes(con, 0)
    assert len(batch["changes"]) == 1
    change = batch["changes"][0]
    assert json.loads(change["nk"]) == [_ATTACK]
    assert change["row"] == {"name": _ATTACK, "notes": _ATTACK}


def test_backfill_treats_pretrigger_values_as_data():
    con = _connection(with_sync=False)
    try:
        con.execute("INSERT INTO people (name, notes) VALUES (?, ?)", (_ATTACK, _ATTACK))
        sync.ensure_sync_schema(con)
        batch = sync.export_changes(con, 0)
        assert len(batch["changes"]) == 1
        assert batch["changes"][0]["row"]["name"] == _ATTACK
    finally:
        con.close()


def test_parent_lookup_and_append_dedup_bind_hostile_natural_keys(con):
    destination = _connection()
    try:
        # Different local ids force natural-key FK resolution on apply.
        destination.execute("INSERT INTO applications (company, role) VALUES ('other', 'role')")
        con.execute("INSERT INTO applications (company, role) VALUES (?, ?)", (_ATTACK, _ATTACK))
        con.execute("INSERT INTO application_events (application_id, type, date, notes) "
                    "VALUES (1, 'note', '2026-10-24', ?)", (_ATTACK,))
        batch = sync.export_changes(con, 0)
        event = next(c for c in batch["changes"] if c["tbl"] == "application_events")
        assert event["row"]["__parent_nk__"] == [_ATTACK, _ATTACK]
        assert sync.apply_changes(destination, batch["changes"])["applied"] == 2
        row = destination.execute("SELECT application_id, notes FROM application_events").fetchone()
        assert tuple(row) == (2, _ATTACK)
        stats = sync.apply_changes(destination, [event])
        assert stats["skipped_dupe"] == 1
        assert destination.execute("SELECT COUNT(*) FROM application_events").fetchone()[0] == 1
    finally:
        destination.close()


def test_employer_upsert_uses_only_fixed_columns_and_bound_values(con):
    certification._upsert_employer(con, {
        "canonical_name": _ATTACK, "street": _ATTACK, "aliases": [_ATTACK],
        "manual_override": True, "created_at": "original",
        "bad) VALUES ('injected'); --": "bad",
    })
    certification._upsert_employer(con, {
        "canonical_name": _ATTACK, "street": "updated", "aliases": [_ATTACK],
        "manual_override": True, "created_at": "must not replace original",
    })
    row = con.execute("SELECT canonical_name, street, aliases, created_at FROM employer_directory").fetchone()
    assert tuple(row) == (_ATTACK, "updated", json.dumps([_ATTACK]), "original")
    assert con.execute("SELECT COUNT(*) FROM employer_directory").fetchone()[0] == 1
    # Manual-override lookup is another dynamic statement; its key stays bound.
    stats = sync.apply_changes(con, [_change("employer_directory", row={
        "canonical_name": _ATTACK, "street": "auto overwrite", "manual_override": 0,
    })])
    assert stats["skipped_guard"] == 1
    assert con.execute("SELECT street FROM employer_directory").fetchone()[0] == "updated"


@pytest.mark.parametrize("table,column", [
    ("stories; DELETE FROM people; --", "id"),
    ("stories", "id FROM stories; DELETE FROM people; --"),
    ("people", "id"),
])
def test_prune_rejects_non_allowlisted_identifiers_before_query(con, table, column):
    executed = []
    con.set_trace_callback(executed.append)
    with pytest.raises(ValueError, match="Unsupported prune"):
        io_sqlite._prune_stale(con, table, column, set())
    assert executed == []


def test_prune_uses_literal_queries_and_binds_stale_ids(con):
    con.executemany("INSERT INTO star_stories (id, title) VALUES (?, ?)", [
        (_ATTACK, "stale"), ("keep", "retained"),
    ])
    con.executemany("INSERT INTO stories (id, title) VALUES (?, ?)", [(1, "stale"), (2, "retained")])
    io_sqlite._prune_stale(con, "star_stories", "id", {"keep"})
    io_sqlite._prune_stale(con, "stories", "id", {2})
    assert [r[0] for r in con.execute("SELECT id FROM star_stories")] == ["keep"]
    assert [r[0] for r in con.execute("SELECT id FROM stories")] == [2]
