"""Founder ledger mutations shared by the CLI and QA review page."""
from lib.discovery import _now, SESSION_KINDS, INCENTIVE_TYPES


def _exists(con, table, row_id):
    queries = {"participants": "SELECT 1 FROM participants WHERE id=?",
               "sessions": "SELECT 1 FROM sessions WHERE id=?"}
    if not con.execute(queries[table], (row_id,)).fetchone():
        raise ValueError("Record not found")


def record_consent(con, participant, version, recording_ok=False, quote_ok=False):
    _exists(con, "participants", participant)
    if not version.strip():
        raise ValueError("Consent version is required")
    con.execute("UPDATE participants SET consent_version=?, consent_recorded_at=?, consent_recording_ok=?, consent_quote_ok=? WHERE id=?",
                (version.strip(), _now(), int(recording_ok), int(quote_ok), participant))


def schedule_session(con, participant, kind="interview", when=None):
    _exists(con, "participants", participant)
    if kind not in SESSION_KINDS:
        raise ValueError("Invalid session kind")
    cur = con.execute("INSERT INTO sessions (participant_id, kind, status, scheduled_for, created_at) VALUES (?, ?, 'scheduled', ?, ?)",
                      (participant, kind, when, _now()))
    con.execute("UPDATE participants SET status=CASE WHEN program='beta' THEN 'enrolled' ELSE 'scheduled' END WHERE id=? AND status='screened'", (participant,))
    return cur.lastrowid


def complete_session(con, session, minutes=0, themes="", notes=None, no_show=False):
    _exists(con, "sessions", session)
    if minutes < 0 or minutes > 1440:
        raise ValueError("Minutes must be between 0 and 1440")
    status = "no_show" if no_show else "completed"
    con.execute("UPDATE sessions SET status=?, duration_minutes=?, themes=?, notes_path=? WHERE id=?",
                (status, minutes, themes, notes, session))
    if not no_show:
        con.execute("UPDATE participants SET status=CASE WHEN program='beta' THEN 'active' ELSE 'completed' END WHERE id=(SELECT participant_id FROM sessions WHERE id=?)", (session,))


def add_quote(con, session, text, public=False):
    _exists(con, "sessions", session)
    if not text.strip():
        raise ValueError("Quote text is required")
    con.execute("INSERT INTO quotes (session_id,text,public) VALUES (?,?,?)", (session, text.strip(), int(public)))


def record_incentive(con, participant, earned_by, type="gift_card", amount=0, reference=None, pending=False):
    _exists(con, "participants", participant)
    if type not in INCENTIVE_TYPES or not 0 <= amount <= 10000:
        raise ValueError("Invalid incentive type or amount")
    con.execute("INSERT INTO incentives (participant_id,earned_by,type,amount_usd,status,sent_at,reference,created_at) VALUES (?,?,?,?,?,?,?,?)",
                (participant, earned_by, type, amount, "pending" if pending else "sent", None if pending else _now(), reference, _now()))


def set_status(con, participant, status):
    _exists(con, "participants", participant)
    if status not in {"dropped", "declined"}:
        raise ValueError("Choose dropped or declined")
    con.execute("UPDATE participants SET status=? WHERE id=?", (status, participant))


ACTIONS = {"consent": record_consent, "schedule": schedule_session, "complete": complete_session,
           "quote": add_quote, "incentive": record_incentive, "status": set_status}


def mutate(con, action, values):
    if action not in ACTIONS:
        raise ValueError("Unknown discovery action")
    with con:
        return ACTIONS[action](con, **values)
