"""
lib/discovery.py — customer-discovery ledger (founder ops, not tenant data).

A standalone SQLite file with its own DDL, kept out of lib/db.py migrations
and the sync TABLE_SPECS on purpose. Two consumers: scripts/discovery_report.py
(the CLI: init, signup import, consent, sessions, incentives, report, snapshot,
findings) and, when it lands, the public /discovery signup route and the
founder-only review page, which call add_signup()/load_ledger()/build_report()
from here so the web surface and the CLI can never disagree about a number.

The counting rules and validation live in build_report(); see the script's
docstring for the human copy.
"""
from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

LEDGER_DEFAULT = Path("data/discovery.db")


def default_ledger_path() -> Path:
    """DISCOVERY_DB env override, else data/discovery.db (never inside a tenant partition)."""
    import os
    return Path(os.environ.get("DISCOVERY_DB") or LEDGER_DEFAULT)
FINDINGS_BEGIN = "<!-- discovery:begin (managed by scripts/discovery_report.py) -->"
FINDINGS_END = "<!-- discovery:end -->"

COUNTABLE_BETA_STATUS = {"enrolled", "active", "completed"}
INTERNAL_SEGMENT = "internal"
SEGMENTS = (
    "job_seeker", "career_changer", "coach", "school", "workforce_program",
    "employer", "other", INTERNAL_SEGMENT,
)
CHANNELS = ("network_free", "linkedin_paid", "discord", "referral", "other")
PROGRAMS = ("interview", "beta")
PARTICIPANT_STATUS = ("screened", "scheduled", "enrolled", "active", "completed", "dropped", "declined")
SESSION_KINDS = ("interview", "beta_session")
SESSION_STATUS = ("scheduled", "completed", "no_show", "cancelled")
INCENTIVE_TYPES = ("gift_card", "pro_access", "none")
INCENTIVE_STATUS = ("pending", "sent")


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


SCHEMA = f"""
CREATE TABLE IF NOT EXISTS program (
    id                        INTEGER PRIMARY KEY CHECK (id = 1),
    name                      TEXT NOT NULL,
    started                   TEXT NOT NULL,
    interview_min_minutes     INTEGER NOT NULL DEFAULT 20,
    beta_sessions_to_complete INTEGER NOT NULL DEFAULT 3,
    consent_version           TEXT NOT NULL DEFAULT '2026-09'
);
CREATE TABLE IF NOT EXISTS participants (
    id                   INTEGER PRIMARY KEY,
    name                 TEXT NOT NULL,
    contact              TEXT NOT NULL,
    segment              TEXT NOT NULL CHECK (segment IN ({_in(SEGMENTS)})),
    channel              TEXT NOT NULL CHECK (channel IN ({_in(CHANNELS)})),
    program              TEXT NOT NULL CHECK (program IN ({_in(PROGRAMS)})),
    status               TEXT NOT NULL CHECK (status IN ({_in(PARTICIPANT_STATUS)})),
    screener_json        TEXT,
    consent_version      TEXT,
    consent_recorded_at  TEXT,
    consent_recording_ok INTEGER NOT NULL DEFAULT 0,
    consent_quote_ok     INTEGER NOT NULL DEFAULT 0,
    notes                TEXT,
    created_at           TEXT NOT NULL,
    UNIQUE (contact)
);
CREATE TABLE IF NOT EXISTS sessions (
    id               INTEGER PRIMARY KEY,
    participant_id   INTEGER NOT NULL REFERENCES participants(id),
    kind             TEXT NOT NULL CHECK (kind IN ({_in(SESSION_KINDS)})),
    status           TEXT NOT NULL CHECK (status IN ({_in(SESSION_STATUS)})),
    scheduled_for    TEXT,
    duration_minutes INTEGER,
    notes_path       TEXT,
    themes           TEXT NOT NULL DEFAULT '',
    created_at       TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS quotes (
    id         INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    text       TEXT NOT NULL,
    public     INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS incentives (
    id             INTEGER PRIMARY KEY,
    participant_id INTEGER NOT NULL REFERENCES participants(id),
    earned_by      TEXT NOT NULL,
    type           TEXT NOT NULL CHECK (type IN ({_in(INCENTIVE_TYPES)})),
    amount_usd     INTEGER NOT NULL DEFAULT 0,
    status         TEXT NOT NULL CHECK (status IN ({_in(INCENTIVE_STATUS)})),
    sent_at        TEXT,
    reference      TEXT,
    created_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_sessions_participant ON sessions(participant_id);
CREATE INDEX IF NOT EXISTS ix_incentives_participant ON incentives(participant_id);
"""


def _now() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def connect(path: Path) -> sqlite3.Connection:
    """Open the ledger with the product's pragmas; creates the schema on first use."""
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA journal_mode = WAL")
    con.executescript(SCHEMA)
    if con.execute("SELECT COUNT(*) FROM program").fetchone()[0] == 0:
        con.execute(
            "INSERT INTO program (id, name, started) VALUES (1, ?, ?)",
            ("jobContext customer discovery", date.today().isoformat()),
        )
    con.commit()
    return con


def ledger_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --- read the ledger into plain records --------------------------------------

def load_ledger(con: sqlite3.Connection) -> dict:
    """Plain-dict view of the tables; build_report works on this shape so the
    counting rules are testable without a database."""
    program = dict(con.execute("SELECT * FROM program WHERE id = 1").fetchone())
    participants = []
    for r in con.execute("SELECT * FROM participants ORDER BY id"):
        d = dict(r)
        d["screener"] = json.loads(d.pop("screener_json") or "null")
        d["consent"] = {
            "version": d.pop("consent_version"),
            "recorded_at": d.pop("consent_recorded_at"),
            "recording_ok": bool(d.pop("consent_recording_ok")),
            "quote_ok": bool(d.pop("consent_quote_ok")),
        }
        participants.append(d)
    quotes_by_session: dict[int, list] = {}
    for r in con.execute("SELECT * FROM quotes ORDER BY id"):
        quotes_by_session.setdefault(r["session_id"], []).append({"text": r["text"], "public": bool(r["public"])})
    sessions = []
    for r in con.execute("SELECT * FROM sessions ORDER BY id"):
        d = dict(r)
        d["themes"] = [t.strip() for t in (d["themes"] or "").split(",") if t.strip()]
        d["quotes"] = quotes_by_session.get(d["id"], [])
        sessions.append(d)
    incentives = [dict(r) for r in con.execute("SELECT * FROM incentives ORDER BY id")]
    return {"program": program, "participants": participants, "sessions": sessions, "incentives": incentives}


# --- the counting rules ------------------------------------------------------

@dataclass
class Report:
    numbers: dict = field(default_factory=dict)
    provenance: dict = field(default_factory=dict)
    breakdowns: dict = field(default_factory=dict)
    themes: list = field(default_factory=list)
    public_quotes: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _has_consent(p: dict) -> bool:
    return bool((p.get("consent") or {}).get("recorded_at"))


def build_report(ledger: dict) -> Report:
    rep = Report()
    program = ledger.get("program") or {}
    min_minutes = int(program.get("interview_min_minutes", 20))
    beta_needed = int(program.get("beta_sessions_to_complete", 3))
    participants = ledger.get("participants") or []
    sessions = ledger.get("sessions") or []
    incentives = ledger.get("incentives") or []

    by_id: dict = {}
    for p in participants:
        pid = p.get("id")
        if pid is None:
            rep.errors.append("participant with no id")
            continue
        if pid in by_id:
            rep.errors.append(f"duplicate participant id {pid}")
        by_id[pid] = p
        if p.get("segment") not in SEGMENTS:
            rep.errors.append(f"participant {pid}: unknown segment {p.get('segment')!r}")
        if p.get("channel") not in CHANNELS:
            rep.errors.append(f"participant {pid}: unknown channel {p.get('channel')!r}")
        if not p.get("screener"):
            rep.warnings.append(f"participant {pid}: no screener on file")

    seen: set = set()
    for s in sessions:
        sid = s.get("id")
        if sid is None or sid in seen:
            rep.errors.append(f"session with missing or duplicate id {sid!r}")
        seen.add(sid)
        if s.get("participant_id") not in by_id:
            rep.errors.append(f"session {sid}: unknown participant {s.get('participant_id')!r}")

    seen = set()
    for i in incentives:
        iid = i.get("id")
        if iid is None or iid in seen:
            rep.errors.append(f"incentive with missing or duplicate id {iid!r}")
        seen.add(iid)
        if i.get("participant_id") not in by_id:
            rep.errors.append(f"incentive {iid}: unknown participant {i.get('participant_id')!r}")
        if i.get("status") == "sent" and not i.get("reference"):
            rep.errors.append(f"incentive {iid}: marked sent with no reference")

    interview_ids: list = []
    interviewed: set = set()
    for s in sessions:
        if s.get("kind") != "interview" or s.get("status") != "completed":
            continue
        p = by_id.get(s.get("participant_id"))
        if p is None:
            continue
        if p.get("segment") == INTERNAL_SEGMENT:
            rep.errors.append(f"session {s['id']}: internal participant has a countable interview")
            continue
        if not _has_consent(p):
            rep.errors.append(f"session {s['id']}: completed interview without consent on file")
            continue
        if int(s.get("duration_minutes") or 0) < min_minutes:
            continue  # a real call, but not a customer interview
        interview_ids.append(s["id"])
        interviewed.add(p["id"])

    beta_enrolled: list = []
    beta_done: Counter = Counter()
    for s in sessions:
        if s.get("kind") == "beta_session" and s.get("status") == "completed":
            beta_done[s.get("participant_id")] += 1
    for pid, p in by_id.items():
        if p.get("program") != "beta" or p.get("status") not in COUNTABLE_BETA_STATUS:
            continue
        if p.get("segment") == INTERNAL_SEGMENT:
            continue
        if not _has_consent(p):
            rep.errors.append(f"participant {pid}: beta participant counted without consent on file")
            continue
        beta_enrolled.append(pid)
    beta_completed = [pid for pid in beta_enrolled if beta_done[pid] >= beta_needed]

    earned: dict = {pid: set() for pid in by_id}
    for sid in interview_ids:
        s = next(x for x in sessions if x["id"] == sid)
        earned[s["participant_id"]].add(str(sid))
    for pid in beta_completed:
        earned[pid].add("beta_complete")

    paid_usd = 0
    paid: dict = {pid: set() for pid in by_id}
    for i in incentives:
        pid = i.get("participant_id")
        if pid not in by_id:
            continue
        basis = str(i.get("earned_by"))
        if basis not in earned[pid]:
            rep.errors.append(f"incentive {i.get('id')}: participant {pid} has not earned {basis!r}")
            continue
        paid[pid].add(basis)
        if i.get("status") == "sent":
            paid_usd += int(i.get("amount_usd") or 0)
    for pid, basis_set in earned.items():
        for basis in sorted(basis_set - paid[pid]):
            if by_id[pid].get("channel") == "network_free":
                continue
            rep.warnings.append(f"participant {pid}: earned {basis} with no incentive row (owed)")

    seg = Counter(by_id[pid]["segment"] for pid in interviewed)
    chan = Counter(by_id[pid]["channel"] for pid in interviewed)
    themes: Counter = Counter()
    for s in sessions:
        countable = s["id"] in interview_ids or (s.get("kind") == "beta_session" and s.get("status") == "completed")
        if countable:
            for t in s.get("themes") or []:
                themes[t] += 1
        for q in s.get("quotes") or []:
            if not q.get("public"):
                continue
            p = by_id.get(s.get("participant_id")) or {}
            if not (p.get("consent") or {}).get("quote_ok"):
                rep.warnings.append(f"session {s['id']}: public quote suppressed, participant consent says quote_ok=false")
                continue
            rep.public_quotes.append({"segment": p.get("segment"), "text": q.get("text")})

    consent_rate = sum(1 for p in by_id.values() if _has_consent(p)) / len(by_id) if by_id else 0.0
    rep.numbers = {
        "customer_interviews_completed": len(interview_ids),
        "unique_participants_interviewed": len(interviewed),
        "beta_testers_enrolled": len(beta_enrolled),
        "beta_testers_completed": len(beta_completed),
        "incentives_paid_usd": paid_usd,
        "consent_on_file_rate": round(consent_rate, 3),
        "participants_total": len(by_id),
        "beta_sessions_to_complete": beta_needed,
    }
    rep.provenance = {
        "customer_interviews_completed": sorted(interview_ids),
        "unique_participants_interviewed": sorted(interviewed),
        "beta_testers_enrolled": sorted(beta_enrolled),
        "beta_testers_completed": sorted(beta_completed),
    }
    rep.breakdowns = {
        "interviews_by_segment": dict(sorted(seg.items())),
        "interviews_by_channel": dict(sorted(chan.items())),
    }
    rep.themes = themes.most_common()
    return rep


# --- rendering ---------------------------------------------------------------

def render_text(rep: Report) -> str:
    out = ["DISCOVERY LEDGER REPORT", ""]
    for k, v in rep.numbers.items():
        out.append(f"  {k:<34} {v}")
    out.append("")
    for name, table in rep.breakdowns.items():
        out.append(f"  {name}:")
        for k, v in table.items():
            out.append(f"    {k:<24} {v}")
    if rep.themes:
        out.append("  themes:")
        out.extend(f"    {n:>3}  {t}" for t, n in rep.themes)
    if rep.warnings:
        out += ["", "  WARNINGS"] + [f"    - {w}" for w in rep.warnings]
    if rep.errors:
        out += ["", "  ERRORS (report withheld)"] + [f"    - {e}" for e in rep.errors]
    return "\n".join(out) + "\n"


def render_findings_block(rep: Report, as_of: str) -> str:
    n = rep.numbers
    lines = [
        FINDINGS_BEGIN,
        f"_Aggregates as of {as_of}. Generated from the private ledger; no participant is identifiable here._",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Customer interviews completed | {n['customer_interviews_completed']} |",
        f"| Unique participants interviewed | {n['unique_participants_interviewed']} |",
        f"| Beta testers enrolled | {n['beta_testers_enrolled']} |",
        f"| Beta testers completed ({n['beta_sessions_to_complete']} sessions) | {n['beta_testers_completed']} |",
        f"| Consent on file | {int(n['consent_on_file_rate'] * 100)}% |",
        "",
    ]
    if rep.breakdowns.get("interviews_by_segment"):
        lines += ["Interviews by segment: " + ", ".join(
            f"{k} {v}" for k, v in rep.breakdowns["interviews_by_segment"].items()), ""]
    if rep.themes:
        lines += ["Most frequent themes:", ""] + [f"- {t} ({c})" for t, c in rep.themes[:10]] + [""]
    if rep.public_quotes:
        lines += ["What participants said (consented, unattributed):", ""]
        for q in rep.public_quotes[:8]:
            lines += [f"> {q['text']}  \n> — {q['segment'].replace('_', ' ')}", ""]
    lines.append(FINDINGS_END)
    return "\n".join(lines)


def write_findings(path: Path, rep: Report, as_of: str) -> bool:
    text = path.read_text(encoding="utf-8")
    start, end = text.find(FINDINGS_BEGIN), text.find(FINDINGS_END)
    if start < 0 or end < 0 or end < start:
        raise SystemExit(f"::error::{path}: managed findings block not found")
    end += len(FINDINGS_END)
    new = text[:start] + render_findings_block(rep, as_of) + text[end:]
    if new == text:
        return False
    path.write_text(new, encoding="utf-8")
    return True


def write_snapshot(ledger_path: Path, rep: Report, as_of: str) -> Path:
    out = ledger_path.with_name(f"discovery_snapshot_{as_of}.json")
    out.write_text(json.dumps({
        "as_of": as_of,
        "ledger_sha256": ledger_sha256(ledger_path),
        "numbers": rep.numbers,
        "provenance": rep.provenance,
        "breakdowns": rep.breakdowns,
        "warnings": rep.warnings,
    }, indent=2) + "\n", encoding="utf-8")
    return out


# --- signup import -------------------------------------------------------------

def _col(headers: list[str], *needles: str) -> str | None:
    for h in headers:
        low = h.lower()
        if any(n in low for n in needles):
            return h
    return None


def _segment_from_answer(answer: str) -> str:
    a = (answer or "").lower()
    if "coach" in a:
        return "coach"
    if "school" in a or "workforce" in a or "program" in a:
        return "school" if "school" in a else "workforce_program"
    if "recruit" in a or "hiring" in a:
        return "employer"
    if "change" in a:
        return "career_changer"
    if "search" in a:
        return "job_seeker"
    return "other"


def import_signups(con: sqlite3.Connection, csv_path: Path, channel: str = "linkedin_paid",
                   program: str = "interview") -> tuple[int, int]:
    """Append screened participants from a Google Forms / Tally CSV export.

    Header matching is by keyword (name, email, search/coach, tool, ai). Rows
    whose contact already exists are skipped, so re-importing a fresh export
    is safe. Returns (inserted, skipped)."""
    with csv_path.open(newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        return 0, 0
    headers = list(rows[0].keys())
    c_name = _col(headers, "name")
    c_mail = _col(headers, "email", "e-mail")
    c_seg = _col(headers, "searching", "coach", "actively")
    c_tools = _col(headers, "tool", "keep track", "use today")
    c_ai = _col(headers, " ai", "assistant")
    if not (c_name and c_mail):
        raise SystemExit("::error::signup CSV needs name and email columns")
    inserted = skipped = 0
    for r in rows:
        contact = (r.get(c_mail) or "").strip()
        if not contact:
            skipped += 1
            continue
        new_id = add_signup(con, r.get(c_name) or "", contact, r.get(c_seg, "") if c_seg else "",
                            r.get(c_tools, "") if c_tools else "", r.get(c_ai, "") if c_ai else "",
                            channel, program)
        if new_id is None:
            skipped += 1
        else:
            inserted += 1
    return inserted, skipped


def add_signup(con: sqlite3.Connection, name: str, contact: str, segment_answer: str,
               current_tools: list[str] | str, ai_assistant: str, channel: str = "linkedin_paid",
               program: str = "interview") -> int | None:
    """Insert one screened participant from a signup (web form or CSV row).

    Returns the new participant id, or None when the contact already exists —
    the web route and the CSV importer both rely on that for idempotency."""
    contact = (contact or "").strip().lower()
    if not contact:
        raise ValueError("contact is required")
    if con.execute("SELECT 1 FROM participants WHERE contact = ?", (contact,)).fetchone():
        return None
    if isinstance(current_tools, str):
        current_tools = [t.strip() for t in current_tools.split(",") if t.strip()]
    screener = {"segment_answer": segment_answer or "", "current_tools": current_tools,
                "ai_assistant": (ai_assistant or "").strip()}
    cur = con.execute(
        "INSERT INTO participants (name, contact, segment, channel, program, status, screener_json, created_at)"
        " VALUES (?, ?, ?, ?, ?, 'screened', ?, ?)",
        ((name or "").strip(), contact, _segment_from_answer(segment_answer), channel, program,
         json.dumps(screener), _now()),
    )
    con.commit()
    return int(cur.lastrowid)
