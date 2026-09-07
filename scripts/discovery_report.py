#!/usr/bin/env python3
"""
Customer-discovery ledger: a founder-ops SQLite file whose numbers are
provenance-gated the way the product's generated claims are.

Every traction number quoted on a pitch application (SXSW Pitch, EDU Launch,
Devpost, investor emails) must be derivable from data/discovery.db by this
script, the same way scripts/update_readme_badges.py derives the README test
and tool counts from real measurements. A number that cannot be recomputed
from records is not quoted.

The ledger is NOT tenant data and NOT part of the MCP surface. It is a
standalone SQLite file (git-ignored by the *.db rule) with its own DDL here,
so lib/db.py migrations and the sync TABLE_SPECS are untouched.

Counting rules (the whole design lives here, so keep them explicit):

  customer_interviews_completed
      sessions with kind == 'interview', status == 'completed',
      duration_minutes >= program.interview_min_minutes, whose participant
      has consent_recorded_at set and is not internal (segment 'internal').
  unique_participants_interviewed
      distinct participants behind the sessions above.
  beta_testers_enrolled
      participants with program == 'beta' and status in
      ('enrolled', 'active', 'completed'), consent required to count.
  beta_testers_completed
      participants with >= program.beta_sessions_to_complete completed
      beta_session rows.
  incentives_paid_usd
      sum of incentive amount_usd with status == 'sent'.

Validation is a hard failure (exit 1), mirroring the badges script: a ledger
that would let a number drift from its records must not produce a number.

  errors   session/incentive pointing at an unknown participant (also
           enforced by FOREIGN KEY); a completed session counted without
           consent on file; an incentive marked sent without a reference; an
           incentive for a condition the participant has not earned; an
           internal participant with a countable session; unknown segment or
           channel (also enforced by CHECK).
  warnings earned incentive with no ledger row (owed) unless the participant
           came in through network_free; participant with no screener; a
           public quote from a participant whose consent says quote_ok is
           false (the quote is suppressed, never published).

Usage:
    python scripts/discovery_report.py init
    python scripts/discovery_report.py import-signups signups.csv
    python scripts/discovery_report.py consent 3 --version 2026-09 [--recording-ok] [--quote-ok]
    python scripts/discovery_report.py session add 3 --kind interview --when 2026-09-18T18:00
    python scripts/discovery_report.py session done 7 --minutes 32 --themes "re-explaining,trust" \
        [--notes data/discovery/s-7.md] [--no-show]
    python scripts/discovery_report.py quote 7 "I retype everything" --public
    python scripts/discovery_report.py incentive 3 --earned-by 7 --type gift_card --amount 25 \
        --reference amazon-XXXX [--pending]
    python scripts/discovery_report.py report            # default when no command given
    python scripts/discovery_report.py check
    python scripts/discovery_report.py snapshot          # data/discovery_snapshot_<date>_<uuid>.json
    python scripts/discovery_report.py findings docs/discovery-findings.md

The snapshot is the provenance record for an application: the numbers, the
row ids behind each one, and a sha256 of the ledger file at the moment the
form was filled in.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import date
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from lib.discovery import (  # noqa: E402
    CHANNELS, INCENTIVE_TYPES, PROGRAMS, SESSION_KINDS, _now, Report, build_report, connect,
    default_ledger_path, import_signups, load_ledger, render_text, write_findings, write_snapshot,
)


from lib.discovery_ops import mutate


# --- CLI ---------------------------------------------------------------------------

def _run_report(con: sqlite3.Connection) -> Report:
    return build_report(load_ledger(con))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ledger", type=Path, default=default_ledger_path())
    ap.add_argument("--as-of", default=date.today().isoformat())
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("init")
    p = sub.add_parser("import-signups"); p.add_argument("csv", type=Path)
    p.add_argument("--channel", default="linkedin_paid", choices=CHANNELS)
    p.add_argument("--program", default="interview", choices=PROGRAMS)
    p = sub.add_parser("consent"); p.add_argument("participant", type=int)
    p.add_argument("--version"); p.add_argument("--recording-ok", action="store_true"); p.add_argument("--quote-ok", action="store_true")
    p = sub.add_parser("session"); ps = p.add_subparsers(dest="scmd")
    a = ps.add_parser("add"); a.add_argument("participant", type=int); a.add_argument("--kind", default="interview", choices=SESSION_KINDS); a.add_argument("--when")
    d = ps.add_parser("done"); d.add_argument("session", type=int); d.add_argument("--minutes", type=int, default=0)
    d.add_argument("--themes", default=""); d.add_argument("--notes"); d.add_argument("--no-show", action="store_true")
    p = sub.add_parser("quote"); p.add_argument("session", type=int); p.add_argument("text"); p.add_argument("--public", action="store_true")
    p = sub.add_parser("incentive"); p.add_argument("participant", type=int); p.add_argument("--earned-by", required=True)
    p.add_argument("--type", default="gift_card", choices=INCENTIVE_TYPES); p.add_argument("--amount", type=int, default=0)
    p.add_argument("--reference"); p.add_argument("--pending", action="store_true")
    p = sub.add_parser("status"); p.add_argument("participant", type=int); p.add_argument("status", choices=("dropped", "declined"))
    sub.add_parser("report"); sub.add_parser("check"); sub.add_parser("snapshot")
    p = sub.add_parser("findings"); p.add_argument("path", type=Path)
    args = ap.parse_args(argv)
    cmd = args.cmd or "report"

    if cmd != "init" and not args.ledger.exists():
        print(f"::error::{args.ledger} not found (run: discovery_report.py init)")
        return 1
    con = connect(args.ledger)
    try:
        if cmd == "init":
            print(f"ledger ready: {args.ledger}")
        elif cmd == "import-signups":
            n, k = import_signups(con, args.csv, args.channel, args.program)
            print(f"imported {n} participant(s), skipped {k}")
        elif cmd in ("consent", "session", "quote", "incentive", "status"):
            values = vars(args).copy()
            for key in ("ledger", "as_of", "cmd", "scmd"):
                values.pop(key, None)
            action = cmd
            if cmd == "consent":
                values["version"] = args.version or con.execute("SELECT consent_version FROM program").fetchone()[0]
            elif cmd == "session":
                action = {"add": "schedule", "done": "complete"}.get(args.scmd, "")
            result = mutate(con, action, values)
            print(f"{action} recorded" + (f": {result}" if result else ""))
        elif cmd in ("report", "check", "snapshot", "findings"):
            rep = _run_report(con)
            if cmd != "check":
                sys.stdout.write(render_text(rep))
            if not rep.ok:
                for e in rep.errors:
                    print(f"::error::{e}")
                return 1
            if cmd == "check":
                n = rep.numbers
                print(f"discovery ledger ok: {n['customer_interviews_completed']} interviews, "
                      f"{n['beta_testers_enrolled']} beta enrolled, {len(rep.warnings)} warning(s)")
            elif cmd == "snapshot":
                con.close(); con = None  # flush WAL before hashing
                print(f"snapshot written: {write_snapshot(args.ledger, rep, args.as_of)}")
            elif cmd == "findings":
                changed = write_findings(args.path, rep, args.as_of)
                print(f"findings {'updated' if changed else 'unchanged'}: {args.path}")
        else:
            ap.print_help()
            return 2
    finally:
        if con is not None:
            con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
