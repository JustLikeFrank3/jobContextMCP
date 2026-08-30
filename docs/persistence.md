# Persistence & Sync

How data is stored, partitioned, synced, and backed up. Derived from `lib/db.py`, `lib/io.py`, `lib/io_sqlite.py`, `lib/sync.py`, `lib/sync_client.py`, `lib/user_provisioning.py`, `lib/work.py`.

## Three storage tiers

1. **SQLite** — one DB per partition at `<DATA_FOLDER>/db/jobcontextmcp.db` (WAL mode, foreign keys on). Core relational tables: applications, application_events, job_queue, people, interviews, rejections, tone_samples, health_log, linkedin_posts, stories, star_stories, personal_profile, plus user_api_keys (global DB), oura_readiness/oura_tokens, chat_sessions/chat_messages, generation_provenance, master_resume_edits, work_items, and the sync journal.
2. **JSON documents** — flat files under `DATA_FOLDER` (`status.json`, `people.json`, `job_queue.json`, `interviews.json`, `eval_results.json`, …). Nine of them have SQLite handlers; the rest are JSON-only.

Every field of a mapped file needs a SQLite home. Under `SQLITE_ONLY` the JSON leg is skipped entirely, so a field with no column is not merely stale on disk — it is never written anywhere. `hbdi_profile`, a singleton blob inside `personal_context.json`, was that case until `personal_profile` (a key/value table) gave it one.
3. **Workspace flat files** — the numbered directory tree (`01-Current-Optimized` … `09-Cover-Letter-PDFs`, `leetcode/`): resumes, cover letters, PDFs, reference materials, prep docs.

### SQLite ⇄ JSON switching

| `USE_SQLITE` | `SQLITE_ONLY` | Mapped file | Behavior |
|---|---|---|---|
| off | — | — | JSON only |
| on | off | yes | SQLite **and** JSON (human-readable audit trail) |
| on | on | yes | SQLite only (cloud + desktop default) |
| on | either | no | JSON always written |

Reads fall back gracefully: a missing/corrupt DB returns the JSON default; writes to SQLite raise on error ("silent data loss is worse than a visible failure").

## Migrations

`lib/db.py` applies an ordered migration list lazily on every connection, tracked by a count-based ledger (`applied_migrations`). The baseline schema lives in `scripts/migrate_to_sqlite.py` (canonical DDL) and `lib/user_provisioning.py` (tenant provisioning) — the three are kept in sync by convention. Global-DB connections skip per-user migrations but still advance the ledger.

## Multi-tenant partitioning

Every tenant's data lives under `DATA_FOLDER/users/{oid}`. Routing is a `ContextVar` set per-request by middleware — authenticated identities are always scoped to their partition; `lib/io` transparently reroutes any `DATA_FOLDER`-relative path. Partitions are provisioned on first access (file-level idempotent: full workspace tree, starter `config.json`, seeded data files, full-schema DB).

Background work never inherits ambient context: the control plane (`lib/work.py`) stores the partition on the `work_items` row and executors enter it from the row — see [control-plane.md](control-plane.md).

## Desktop ⇄ cloud sync

Journal-based bidirectional sync (`lib/sync.py`), configured on the desktop with `cloud_sync_url` + `cloud_sync_pat` (a `jcmcp_` PAT from the dashboard); auto-sync runs every 15 minutes when enabled.

- **Journal**: AFTER-triggers on synced tables write to `sync_log`; no application write path changes. Applying remote changes flips an `applying` flag the triggers check, preventing echo loops. Rows predating a table's triggers are journaled once by a backfill, guarded per table (`sync_meta` key `journal_backfill:<table>`) so a table added to `TABLE_SPECS` later still backfills on installs that already ran an earlier backfill.
- **Row semantics**: upsert tables (applications, job_queue, people, interviews, oura_readiness, stories, star_stories, personal_profile) resolve conflicts last-writer-wins by timestamp, deletes travel as tombstones; append tables (application_events, rejections, health_log, linkedin_posts, tone_samples) are insert-if-absent so replays dedupe by construction.
- **Cross-replica identity**: integer ids never leave the machine — rows are identified by natural keys; child rows carry the parent's natural key and re-resolve on apply. `star_stories` is the exception: its id is a hand-authored TEXT slug, stable everywhere, so it *is* the key and travels.
- **Coverage is the gap to watch**: a table mapped in `lib/io_sqlite.py` but missing from `TABLE_SPECS` silently never syncs, and file sync cannot cover for it (under `SQLITE_ONLY` the JSON is never written, and a JSON received by file sync is never imported back into SQLite). `test_every_sqlite_mapped_table_row_syncs` fails on that drift.
- **File sync**: sha256 manifest diff against a baseline; changed-both-sides conflicts keep the remote copy as a `" (sync conflict from cloud)"` sibling instead of overwriting. Manifest keys are always POSIX-separated (a Windows peer would otherwise fork every key and re-transfer the workspace both ways). Databases, `config.json`, backups, and index artifacts stay machine-local; per-file transfer errors skip-and-report rather than wedging the pass.
- **File deletions**: manifests only describe what exists, so a delete records a `file_tombstones` row (rel + sha256 + deleted_at) that travels the row journal like any other upsert table. Each side reconciles rows against its tree: a file at a tombstoned rel with mtime ≤ deleted_at is a stale copy and is removed; mtime > deleted_at means it was recreated after the deletion, so the file wins and the tombstone clears (journaled, so the clearing propagates). The cloud reconciles inside `/api/sync/files/manifest` (the client pushes rows first, so a deletion clears the manifest within the same pass) and `/api/sync/files/put` refuses content older than the tombstone — that guard is what stops a peer on a pre-tombstone build from resurrecting the file. Deletions enter through the Materials dashboard (untracked-file delete/associate) and the `materials.delete` MCP action; tombstones prune after 90 days.
- **Contact block**: `config.json` never syncs, so the `contact` block is exchanged separately, fill-empty-only in both directions.

## Backup / export / import

| Mechanism | What it does |
|---|---|
| `GET /api/dashboard/export` | Zip of the caller's whole data root (requires a user session; excludes WAL sidecars) |
| `POST /desktop/import-workspace` | Restores an export zip; the existing data dir is moved aside (`-backup-<timestamp>`), never deleted; restart required |
| `scripts/pi-backup.sh` | Nightly timer on the Pi: rsync snapshot + consistent `sqlite3 .backup` per DB, 7 retained |
| Dual-write JSON | The non-`SQLITE_ONLY` mode keeps JSON as a human-readable audit trail |
| `scripts/migrate_to_sqlite.py` | One-time JSON → SQLite bootstrap (operates on `data_dev/`; recreates the DB each run) |
