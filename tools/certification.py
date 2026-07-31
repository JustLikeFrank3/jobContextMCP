"""Weekly work-search certification tools.

Unemployment claim certification requires N verifiable work-search activities
per week (N=3 in Georgia), each with employer, business address, website,
position, date, contact method, contact name, and result. The activities
already exist in the workspace (applications, interviews) — these tools
assemble them into immutable weekly report snapshots, enrich employer
addresses through a cache-first directory, and export in portal-ready formats.

Principle (same ethos as the provenance gate): certification entries must
trace to logged events. The tool never invents an activity — every entry
carries the source_event_ids it derives from, and export is blocked for any
entry without one. If the week has fewer than N qualifying activities, the
report says so loudly rather than padding.

Tools exposed:
    - weekly_certification_report
    - list_certification_reports
    - export_certification_report
    - swap_certification_entry
    - employer_lookup
    - employer_override
    - certification_state_profile
"""
from __future__ import annotations

import csv
import datetime
import hashlib
import io
import json
import re
from typing import Literal

from lib import config
from lib.db import get_connection
from lib.io import _load_json, _now, _save_json

# ── State profile ─────────────────────────────────────────────────────────────

DEFAULT_STATE_PROFILE: dict = {
    "state": "GA",
    "min_activities_per_week": 3,
    "week_ends_on": "Saturday",
    "accepted_activity_kinds": [
        "application_submitted",
        "interview_attended",
        "employer_followup",
        "resume_to_recruiter",
        "screening_completed",
    ],
    # Conservative default — GDOL guidance on answered inbound contacts is
    # unverified; flip via certification(action="state_profile", ...).
    "counts_inbound_recruiter": False,
    "counts_materials_prep": False,
    "required_fields": [
        "employer", "address", "position", "date", "method", "contact", "result",
    ],
}

_WEEKDAYS = (
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
)


def get_state_profile() -> dict:
    """Active certification rules: stored profile merged over GA defaults."""
    stored = _load_json(config.STATE_PROFILE_FILE, {})
    if not isinstance(stored, dict):
        stored = {}
    return {**DEFAULT_STATE_PROFILE, **stored}


def is_configured() -> bool:
    """True once the user has saved a profile or generated a report."""
    if _load_json(config.STATE_PROFILE_FILE, None) is not None:
        return True
    with get_connection() as con:
        row = con.execute("SELECT COUNT(*) FROM certification_report").fetchone()
    return bool(row[0])


def certification_state_profile(
    mode: Literal["get", "set"] = "get",
    state: str = "",
    min_activities_per_week: int = 0,
    week_ends_on: str = "",
    accepted_activity_kinds: list[str] | None = None,
    counts_inbound_recruiter: bool | None = None,
    counts_materials_prep: bool | None = None,
) -> str:
    """Read or update the certification rules for this workspace's state.

    Ships with Georgia defaults (3 activities/week, week ends Saturday);
    other states are config entries, not code.
    """
    profile = get_state_profile()
    if mode == "get":
        lines = [f"═══ CERTIFICATION PROFILE ({profile['state']}) ═══"]
        for key in DEFAULT_STATE_PROFILE:
            lines.append(f"  {key}: {profile[key]}")
        return "\n".join(lines)

    updates: dict = {}
    if state.strip():
        updates["state"] = state.strip().upper()
    if min_activities_per_week:
        if not 1 <= int(min_activities_per_week) <= 14:
            return "✗ min_activities_per_week must be between 1 and 14."
        updates["min_activities_per_week"] = int(min_activities_per_week)
    if week_ends_on.strip():
        day = week_ends_on.strip().capitalize()
        if day not in _WEEKDAYS:
            return f"✗ week_ends_on must be one of: {', '.join(_WEEKDAYS)}."
        updates["week_ends_on"] = day
    if accepted_activity_kinds:
        updates["accepted_activity_kinds"] = [
            str(k).strip() for k in accepted_activity_kinds if str(k).strip()
        ]
    if counts_inbound_recruiter is not None:
        updates["counts_inbound_recruiter"] = bool(counts_inbound_recruiter)
    if counts_materials_prep is not None:
        updates["counts_materials_prep"] = bool(counts_materials_prep)
    if not updates:
        return "✗ Nothing to update — pass at least one profile field."

    stored = _load_json(config.STATE_PROFILE_FILE, {})
    if not isinstance(stored, dict):
        stored = {}
    stored.update(updates)
    stored["updated_at"] = _now()
    _save_json(config.STATE_PROFILE_FILE, stored)
    merged = {**DEFAULT_STATE_PROFILE, **stored}
    return (
        f"✓ Certification profile updated ({', '.join(sorted(updates))}). "
        f"Now: {merged['state']}, {merged['min_activities_per_week']}/week, "
        f"week ends {merged['week_ends_on']}."
    )


# ── Week windows ──────────────────────────────────────────────────────────────

def _week_ending_date(profile: dict, week_ending: str = "") -> "datetime.date | str":
    """Resolve the report's week-ending date (str return = error message)."""
    end_day = _WEEKDAYS.index(profile.get("week_ends_on", "Saturday"))
    if week_ending.strip():
        try:
            end = datetime.date.fromisoformat(week_ending.strip())
        except ValueError:
            return f"✗ week_ending must be YYYY-MM-DD, got {week_ending!r}."
        if end.weekday() != end_day:
            return (
                f"✗ {end.isoformat()} is a {_WEEKDAYS[end.weekday()]}, but this "
                f"profile's weeks end on {profile['week_ends_on']}."
            )
        return end
    today = datetime.date.today()
    offset = (today.weekday() - end_day) % 7
    return today - datetime.timedelta(days=offset)


def current_week_ending(profile: dict) -> datetime.date:
    """The RUNNING week's end date (today or the next configured week-end).

    Distinct from _week_ending_date's no-arg default, which resolves the
    most recently CLOSED week (what a Sunday-morning report generation
    wants). Live progress — the Home card's "2/3 so far" — tracks the week
    still in flight.
    """
    end_day = _WEEKDAYS.index(profile.get("week_ends_on", "Saturday"))
    today = datetime.date.today()
    return today + datetime.timedelta(days=(end_day - today.weekday()) % 7)


def _week_window(end: datetime.date) -> tuple[datetime.date, datetime.date]:
    return end - datetime.timedelta(days=6), end


def _in_window(raw_date: str, start: datetime.date, end: datetime.date) -> bool:
    day = _parse_date(raw_date)
    return day is not None and start <= day <= end


def _parse_date(raw: str) -> "datetime.date | None":
    raw = str(raw or "").strip()[:10]
    try:
        return datetime.date.fromisoformat(raw)
    except ValueError:
        return None


# ── Activity derivation ───────────────────────────────────────────────────────

# Strength order — strongest evidence first; the report leads with these.
_KIND_STRENGTH = {
    "interview_attended": 0,
    "application_submitted": 1,
    "screening_completed": 2,
    "resume_to_recruiter": 3,
    "employer_followup": 4,
    "inbound_recruiter": 5,
    "materials_prep": 6,
}

_SCREEN_INTERVIEW_TYPES = {"phone_screen", "recruiter_screen", "screening"}
_FOLLOWUP_EVENT_TYPES = {"follow_up_sent", "outreach_sent", "reply_sent"}
_MATERIAL_RE = re.compile(r"\bresume|\bcover letter|\bmaterials? attach", re.I)
_CLOSED_STATUSES = ("closed", "rejected", "withdrawn", "passed")


def _event_id(*parts: str) -> str:
    """Stable short id for a source record (events carry no ids of their own)."""
    return hashlib.sha1("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:12]


def _method_from(notes: str, default: str) -> str:
    lowered = str(notes or "").lower()
    for needle, method in (
        ("linkedin", "LinkedIn message"),
        ("inmail", "LinkedIn InMail"),
        ("email", "Email"),
        ("called", "Phone"),
        ("phone", "Phone"),
        ("portal", "Online application"),
    ):
        if needle in lowered:
            return method
    return default


def _contact_name(app: dict) -> str:
    raw = str(app.get("contact", "") or "").strip()
    if not raw:
        return ""
    # "Kye Matthews-Mason (recruiter)" / "Monica Kareem (Sr. Recruiter) | ..." →
    # first name-ish segment before any annotation.
    return re.split(r"[(|;\n]|—| - ", raw)[0].strip().rstrip(",")


def _derive_result(app: dict, activity_date: str) -> str:
    """Auto-derive the entry's result from subsequent events on the thread."""
    after: list[tuple[str, str]] = []
    for event in app.get("events", []) or []:
        ev_date = str(event.get("date", "") or "")[:10]
        if ev_date and ev_date > activity_date:
            after.append((ev_date, str(event.get("type", "") or "")))
    for ev_date, ev_type in sorted(after):
        if ev_type == "rejected":
            return f"Not selected, notified {ev_date}"
        if ev_type == "interview_scheduled":
            return f"Interview scheduled ({ev_date})"
        if ev_type in ("reply_received", "recruiter_contact"):
            return f"Employer responded {ev_date}"
    status = str(app.get("status", "") or "").lower()
    if any(s in status for s in _CLOSED_STATUSES):
        return "Position closed"
    return "Awaiting response"


def _load_applications() -> list[dict]:
    data = _load_json(config.STATUS_FILE, {"applications": []})
    apps = data.get("applications", []) if isinstance(data, dict) else []
    return [a for a in apps if isinstance(a, dict)]


def _load_interviews() -> list[dict]:
    data = _load_json(config.INTERVIEWS_FILE, {"interviews": []})
    ivs = data.get("interviews", []) if isinstance(data, dict) else []
    return [i for i in ivs if isinstance(i, dict)]



_JOB_BOARD_HOSTS = {
    "linkedin.com", "indeed.com", "workforcenow.adp.com", "greenhouse.io",
    "lever.co", "ashbyhq.com", "glassdoor.com", "ziprecruiter.com",
    "myworkdayjobs.com",
}


def _website_hint_from(*texts: str) -> str:
    """First employer-domain URL found in logged text, as a scrape base.

    Job-board and ATS hosts are skipped — jobs.mercedes-benz.com yields
    https://mercedes-benz.com, but a LinkedIn posting URL yields nothing.
    Provenance-clean: the hint comes from logged data, never model memory.
    """
    for text in texts:
        for match in re.finditer(r"https?://([^/\s)\]>\"']+)", str(text or "")):
            host = match.group(1).lower().split(":")[0]
            if any(host == h or host.endswith("." + h) for h in _JOB_BOARD_HOSTS):
                continue
            parts = [p for p in host.split(".") if p]
            if len(parts) >= 2:
                registrable = ".".join(parts[-2:])
                if parts[0] in ("jobs", "careers", "apply", "www") or len(parts) == 2:
                    return f"https://{registrable}"
                return f"https://{host}"
    return ""


def derive_activities(start: datetime.date, end: datetime.date, profile: dict) -> list[dict]:
    """All qualifying work-search activities inside [start, end], from logged
    events only. Each activity carries the source_event_ids it derives from."""
    accepted = set(profile.get("accepted_activity_kinds", []))
    if profile.get("counts_inbound_recruiter"):
        accepted.add("inbound_recruiter")
    activities: list[dict] = []
    seen_ids: set[str] = set()

    def add(kind: str, company: str, position: str, date: str, method: str,
            contact: str, result: str, source_ids: list[str],
            website_hint: str = "") -> None:
        if kind not in accepted or not company.strip():
            return
        primary = source_ids[0]
        if primary in seen_ids:
            return
        seen_ids.add(primary)
        norm = re.sub(r"[^a-z0-9]", "", company.lower())
        for existing in activities:
            if existing["kind"] != kind or existing["date"] != date:
                continue
            if existing["position"].strip().lower() != position.strip().lower():
                continue
            e_norm = re.sub(r"[^a-z0-9]", "", existing["employer"].lower())
            if norm and e_norm and (norm.startswith(e_norm) or e_norm.startswith(norm)):
                # Same activity logged under an employer alias (e.g. "Mercedes"
                # vs "Mercedes-Benz USA") — merge, keep the longer name.
                existing["source_event_ids"] = sorted(
                    set(existing["source_event_ids"]) | set(source_ids)
                )
                if len(company.strip()) > len(existing["employer"]):
                    existing["employer"] = company.strip()
                if contact and not existing.get("contact"):
                    existing["contact"] = contact
                return
        activities.append({
            "website_hint": website_hint,
            "kind": kind,
            "strength": _KIND_STRENGTH.get(kind, 9),
            "employer": company.strip(),
            "position": position.strip(),
            "date": date,
            "method": method,
            "contact": contact,
            "result": result,
            "source_event_ids": source_ids,
        })

    # 1. Interviews attended / screenings completed — interview debriefs.
    for iv in _load_interviews():
        date = str(iv.get("interview_date", "") or iv.get("timestamp", ""))[:10]
        if not _in_window(date, start, end):
            continue
        iv_type = str(iv.get("interview_type", "") or "").lower()
        kind = (
            "screening_completed"
            if iv_type in _SCREEN_INTERVIEW_TYPES
            else "interview_attended"
        )
        fmt = str(iv.get("interview_format", "") or "").lower()
        method = {
            "video": "Video interview",
            "phone": "Phone interview",
            "onsite": "In-person interview",
            "in_person": "In-person interview",
        }.get(fmt, "Interview")
        add(
            kind,
            str(iv.get("company", "")),
            str(iv.get("role", "")),
            date,
            method,
            str(iv.get("interviewer", "") or ""),
            "Interview completed",
            [_event_id("interview", iv.get("timestamp", ""), iv.get("company", ""), iv.get("role", ""))],
        )

    # 2. Application events.
    for app in _load_applications():
        company = str(app.get("company", "") or "")
        position = str(app.get("role", "") or "")
        contact = _contact_name(app)
        hint = _website_hint_from(
            app.get("notes", ""), app.get("next_steps", ""),
            *[e.get("notes", "") for e in (app.get("events", []) or [])],
        )
        status_active = not any(
            s in str(app.get("status", "") or "").lower() for s in _CLOSED_STATUSES
        )
        for event in app.get("events", []) or []:
            ev_type = str(event.get("type", "") or "")
            ev_date = str(event.get("date", "") or "")[:10]
            if not _in_window(ev_date, start, end):
                continue
            notes = str(event.get("notes", "") or "")
            source = [_event_id("app_event", company, ev_type, event.get("date", ""), notes[:80])]
            if ev_type == "applied":
                add("application_submitted", company, position, ev_date,
                    _method_from(notes, "Online application"), contact,
                    _derive_result(app, ev_date), source, website_hint=hint)
            elif ev_type == "phone_screen":
                add("screening_completed", company, position, ev_date,
                    _method_from(notes, "Phone screen"), contact,
                    _derive_result(app, ev_date), source)
            elif ev_type in _FOLLOWUP_EVENT_TYPES and _MATERIAL_RE.search(notes):
                add("resume_to_recruiter", company, position, ev_date,
                    _method_from(notes, "Email"), contact,
                    _derive_result(app, ev_date), source)
            elif ev_type in _FOLLOWUP_EVENT_TYPES and status_active:
                add("employer_followup", company, position, ev_date,
                    _method_from(notes, "Email"), contact,
                    _derive_result(app, ev_date), source)
            elif ev_type == "recruiter_contact":
                add("inbound_recruiter", company, position, ev_date,
                    _method_from(notes, "Recruiter contact"), contact,
                    _derive_result(app, ev_date), source)

        # An application whose applied_date falls in-window but has no
        # "applied" event still counts — the transition is the logged fact.
        applied = str(app.get("applied_date", "") or "")[:10]
        if _in_window(applied, start, end):
            add("application_submitted", company, position, applied,
                "Online application", contact, _derive_result(app, applied),
                [_event_id("applied_date", company, position, applied)],
                website_hint=hint)

    return activities


def select_entries(activities: list[dict], target: int) -> tuple[list[dict], list[dict]]:
    """Pick the report's entries: rank by strength → prefer distinct employers
    → distinct kinds → spread across days. Remainder become alternates.
    NEVER pads: returns fewer than target when the week came up short."""
    pool = sorted(activities, key=lambda a: (a["strength"], a["date"]))
    picked: list[dict] = []
    while pool and len(picked) < target:
        employers = {p["employer"].casefold() for p in picked}
        kinds = {p["kind"] for p in picked}
        days = {p["date"] for p in picked}
        best = min(
            pool,
            key=lambda a: (
                a["employer"].casefold() in employers,
                a["kind"] in kinds,
                a["date"] in days,
                a["strength"],
                a["date"],
            ),
        )
        pool.remove(best)
        picked.append(best)
    picked.sort(key=lambda a: (a["strength"], a["date"]))
    return picked, pool


# ── Employer directory + address enrichment ───────────────────────────────────

_STALE_DAYS = 90
_AGENCY_RE = re.compile(
    r"^unknown\s*\((?P<agency>.+?)\s+client\)|\(via\s+(?P<via>[^)]+)\)", re.I
)
# Street address: "123 Any St[reet …], City, ST 12345" — deliberately strict;
# a wrong address on a certification is worse than a flagged gap.
_ADDRESS_RE = re.compile(
    r"(?P<street>(?:\d{1,6}|One|Two|Three|Four|Five|Ten)\s+[A-Za-z0-9 .'-]{3,60}"
    r"(?:Street|St|Avenue|Ave|Boulevard|Blvd|Drive|Dr|Road|Rd|Lane|Ln|Way|"
    r"Court|Ct|Place|Pl|Parkway|Pkwy|Circle|Cir|Highway|Hwy|Suite [\w-]+)\.?)"
    r"[,\s]+(?P<city>[A-Za-z .'-]{2,40})[,\s]+"
    r"(?P<state>[A-Z]{2})[,\s]+(?P<zip>\d{5}(?:-\d{4})?)"
)


def employer_of_record(company: str) -> str:
    """The verifiable employer for a certification entry.

    When the employer of record is a staffing agency and the client is
    undisclosed ("Unknown (SRG Client)", "Role (via Insight Global)"), the
    agency is the contactable party — enrich and list the agency.
    """
    match = _AGENCY_RE.search(str(company or ""))
    if match:
        return (match.group("agency") or match.group("via") or "").strip()
    return str(company or "").strip()


def _row_to_dict(row) -> dict:
    d = dict(row)
    try:
        d["aliases"] = json.loads(d.get("aliases") or "[]")
    except (TypeError, ValueError):
        d["aliases"] = []
    return d


def _find_employer(con, name: str) -> "dict | None":
    folded = name.strip().casefold()
    for row in con.execute("SELECT * FROM employer_directory"):
        d = _row_to_dict(row)
        names = [d["canonical_name"], *d["aliases"]]
        if any(str(n).strip().casefold() == folded for n in names):
            return d
    return None


def _is_stale(row: dict) -> bool:
    if row.get("manual_override"):
        return False
    verified = _parse_date(str(row.get("verified_at", "")))
    if verified is None:
        return True
    return (datetime.date.today() - verified).days > _STALE_DAYS


def _has_address(row: dict) -> bool:
    return bool(str(row.get("street", "")).strip() and str(row.get("city", "")).strip())


def _upsert_employer(con, values: dict) -> None:
    cols = (
        "canonical_name", "aliases", "street", "city", "state", "zip", "website",
        "phone", "address_kind", "source_url", "confidence", "verified_at",
        "manual_override", "created_at", "updated_at",
    )
    row = {c: values.get(c, "") for c in cols}
    row["aliases"] = json.dumps(values.get("aliases", []) or [])
    row["manual_override"] = 1 if values.get("manual_override") else 0
    row["created_at"] = values.get("created_at") or _now()
    row["updated_at"] = _now()
    placeholders = ", ".join("?" for _ in cols)
    updates = ", ".join(f"{c}=excluded.{c}" for c in cols if c != "created_at")
    con.execute(
        f"INSERT INTO employer_directory ({', '.join(cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT(canonical_name) DO UPDATE SET {updates}",
        tuple(row[c] for c in cols),
    )


def _fetch_page(url: str) -> str:
    """Fetch a page as text (Jina Reader proxy). Isolated for tests."""
    from tools.job_scraper import _fetch_jina

    return _fetch_jina(url)


def _web_search_address(company: str) -> "tuple[dict, str] | None":
    """SerpAPI fallback: search the open web for a business address.

    Returns (address fields, source_url) or None. Keyless mode returns None —
    addresses are never generated from model memory; page-sourced or manual only.
    """
    api_key = getattr(config, "SERPAPI_KEY", "")
    if not api_key:
        return None
    import httpx

    try:
        resp = httpx.get(
            "https://serpapi.com/search.json",
            params={
                "engine": "google",
                "q": f"{company} corporate office business address",
                "api_key": api_key,
            },
            timeout=20,
        )
        resp.raise_for_status()
        payload = resp.json()
    except Exception:  # noqa: BLE001 — enrichment is best-effort
        return None
    blobs: list[tuple[str, str]] = []
    kg = payload.get("knowledge_graph", {}) or {}
    if kg.get("address"):
        blobs.append((str(kg["address"]), str(kg.get("website", "") or "serpapi:knowledge_graph")))
    for result in payload.get("organic_results", []) or []:
        blobs.append((str(result.get("snippet", "") or ""), str(result.get("link", "") or "")))
    for text, source in blobs:
        match = _ADDRESS_RE.search(text)
        if match:
            return dict(match.groupdict()), source
    return None


def _ddg_search_address(company: str) -> "tuple[dict, str] | None":
    """Keyless fallback: DuckDuckGo HTML results via the page-fetch proxy.

    No API key required, so deployments without a serpapi_key still enrich.
    A results page mixes many businesses (ads, directories), so an address
    only counts when the company's name appears just before it — same
    snippet, not merely same page. Nothing comes from model memory.
    """
    from urllib.parse import quote_plus

    url = ("https://html.duckduckgo.com/html/?q="
           + quote_plus(f"{company} corporate office business address"))
    try:
        text = _fetch_page(url)
    except Exception:  # noqa: BLE001 — enrichment is best-effort
        return None
    tokens = re.findall(r"[a-z0-9]+", company.lower())
    needle = next((t for t in tokens if len(t) >= 3), "")
    if not needle:
        return None
    for match in _ADDRESS_RE.finditer(text):
        window = re.sub(
            r"[^a-z0-9]", "", text[max(0, match.start() - 300):match.start()].lower()
        )
        if needle in window:
            return dict(match.groupdict()), url
    return None


def _llm_extract_address(page_text: str, company: str) -> "dict | None":
    """Optional LLM extraction from a fetched page (BYOK-consistent).

    Keyless mode returns None and the caller falls back to the regex
    extractor. The model only ever extracts from page text it is shown —
    never from memory — and the result is still validated by _ADDRESS_RE.
    """
    try:
        client, model = config.get_llm_client(task="certification")
    except Exception:  # noqa: BLE001
        return None
    if client is None:
        return None
    from lib.openai_calls import create_chat_completion

    try:
        response = create_chat_completion(
            client,
            label="address_extract",
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Extract the US business street address for the named "
                        "company from the page text. Reply with exactly one "
                        "line: street, city, ST zip — or NONE if the page does "
                        "not contain one. Never invent an address."
                    ),
                },
                {"role": "user", "content": f"Company: {company}\n\n{page_text[:6000]}"},
            ],
            temperature=0,
            max_tokens=100,
        )
        line = (response.choices[0].message.content or "").strip()
    except Exception:  # noqa: BLE001
        return None
    match = _ADDRESS_RE.search(line)
    return dict(match.groupdict()) if match else None


def _scrape_address(website: str, company: str) -> "tuple[dict, str] | None":
    """Try the company's own site: contact/about/locations pages."""
    base = website.rstrip("/")
    for path in ("", "/contact", "/about", "/locations", "/contact-us"):
        url = f"{base}{path}"
        try:
            text = _fetch_page(url)
        except Exception:  # noqa: BLE001 — try the next page
            continue
        match = _ADDRESS_RE.search(text)
        if match:
            return dict(match.groupdict()), url
        extracted = _llm_extract_address(text, company)
        if extracted:
            return extracted, url
    return None


def enrich_employer(name: str, website_hint: str = "") -> dict:
    """Resolve one employer's directory row, enriching if missing or stale.

    Cache-first; manual_override rows are never auto-overwritten. Every
    stored address carries its source_url. Returns the (possibly
    unenriched) row dict; callers flag needs_address when no address landed.
    """
    canonical = employer_of_record(name)
    with get_connection() as con:
        row = _find_employer(con, canonical)
    if row and (_has_address(row) and not _is_stale(row)):
        return row

    website = (website_hint or (row or {}).get("website", "") or "").strip()
    found: "tuple[dict, str] | None" = None
    if website:
        found = _scrape_address(website, canonical)
        confidence = "verified" if found else ""
    if not found:
        found = _web_search_address(canonical) or _ddg_search_address(canonical)
        confidence = "scraped" if found else ""
        # An address found on the company's own domain upgrades to verified.
        if found and website:
            from urllib.parse import urlparse

            own = urlparse(website).netloc.removeprefix("www.")
            src = urlparse(found[1]).netloc.removeprefix("www.")
            if own and own == src:
                confidence = "verified"

    values = dict(row or {"canonical_name": canonical, "aliases": []})
    if name.strip() and name.strip() != canonical:
        aliases = set(values.get("aliases", []) or [])
        aliases.add(name.strip())
        values["aliases"] = sorted(aliases)
    values.setdefault("canonical_name", canonical)
    values["website"] = website or values.get("website", "")
    if found:
        fields, source_url = found
        values.update({
            "street": fields.get("street", ""),
            "city": fields.get("city", ""),
            "state": fields.get("state", ""),
            "zip": fields.get("zip", ""),
            "source_url": source_url,
            "confidence": confidence or "scraped",
            "verified_at": datetime.date.today().isoformat(),
        })
    with get_connection() as con:
        existing = _find_employer(con, canonical)
        if existing and existing.get("manual_override"):
            return existing  # never auto-overwrite a human correction
        _upsert_employer(con, values)
        return _find_employer(con, canonical) or values


def _format_address(row: dict) -> str:
    if not _has_address(row):
        return ""
    parts = [str(row.get("street", "")).strip(), str(row.get("city", "")).strip()]
    tail = " ".join(p for p in (str(row.get("state", "")).strip(), str(row.get("zip", "")).strip()) if p)
    if tail:
        parts.append(tail)
    return ", ".join(p for p in parts if p)


def lookup_employer(name: str) -> str:
    """Read (and refresh, if stale) one employer directory row."""
    if not str(name or "").strip():
        return "✗ employer name is required."
    row = enrich_employer(name)
    address = _format_address(row) or "— none on file (needs_address)"
    flags = []
    if row.get("manual_override"):
        flags.append("manual override — never auto-updated")
    if _is_stale(row):
        flags.append(f"stale (verified_at > {_STALE_DAYS}d ago)")
    return "\n".join(filter(None, [
        f"═══ {row.get('canonical_name', name)} ═══",
        f"  address: {address}",
        f"  website: {row.get('website') or '—'}",
        f"  phone: {row.get('phone') or '—'}",
        f"  kind: {row.get('address_kind') or 'hq'}"
        f" · confidence: {row.get('confidence') or '—'}"
        f" · verified: {row.get('verified_at') or 'never'}",
        f"  source: {row.get('source_url') or '—'}",
        f"  aliases: {', '.join(row.get('aliases', [])) or '—'}",
        ("  ⚠ " + "; ".join(flags)) if flags else "",
    ]))


def override_employer(name: str, fields: dict | str | None = None) -> str:
    """Manually correct a directory row. Sets manual_override — the
    enrichment pipeline will never overwrite it again."""
    if not str(name or "").strip():
        return "✗ employer name is required."
    if isinstance(fields, str) and fields.strip():
        try:
            fields = json.loads(fields)
        except ValueError:
            return "✗ fields must be JSON, e.g. {\"street\": \"123 Main St\", \"city\": \"Atlanta\", \"state\": \"GA\", \"zip\": \"30303\"}."
    if not isinstance(fields, dict) or not fields:
        return (
            "✗ fields is required — e.g. {\"street\": \"123 Main St\", "
            "\"city\": \"Atlanta\", \"state\": \"GA\", \"zip\": \"30303\"}."
        )
    allowed = {
        "canonical_name", "street", "city", "state", "zip", "website",
        "phone", "address_kind", "aliases",
    }
    unknown = set(fields) - allowed
    if unknown:
        return f"✗ Unknown field(s): {', '.join(sorted(unknown))}. Allowed: {', '.join(sorted(allowed))}."
    canonical = employer_of_record(name)
    with get_connection() as con:
        row = _find_employer(con, canonical) or {
            "canonical_name": canonical, "aliases": [],
        }
        row.update(fields)
        row["manual_override"] = True
        row["confidence"] = "manual"
        row["source_url"] = "manual"
        row["verified_at"] = datetime.date.today().isoformat()
        _upsert_employer(con, row)
    return f"✓ {canonical} corrected and locked (manual_override — enrichment will not touch it)."


# ── Reports ───────────────────────────────────────────────────────────────────

def _entry_payload(activity: dict, directory_row: dict) -> dict:
    address = _format_address(directory_row)
    entry = {
        "employer": directory_row.get("canonical_name") or activity["employer"],
        "address": address,
        "website": directory_row.get("website", ""),
        "position": activity["position"],
        "date": activity["date"],
        "method": activity["method"],
        "contact": activity["contact"],
        "result": activity["result"],
        "kind": activity["kind"],
        "source_event_ids": activity["source_event_ids"],
    }
    if not address:
        entry["needs_address"] = True
    return entry


def _audit_append(record: dict) -> None:
    """Dual-write JSON audit trail beside the SQLite rows."""
    data = _load_json(config.CERTIFICATION_AUDIT_FILE, {"reports": []})
    if not isinstance(data, dict):
        data = {"reports": []}
    data.setdefault("reports", []).append(record)
    _save_json(config.CERTIFICATION_AUDIT_FILE, data)


def _insert_report(con, week_ending: str, profile: dict, entries: list[dict],
                   alternates: list[dict], gaps: list[str]) -> tuple[int, int]:
    row = con.execute(
        "SELECT COALESCE(MAX(version), 0) FROM certification_report WHERE week_ending = ?",
        (week_ending,),
    ).fetchone()
    version = int(row[0]) + 1
    cur = con.execute(
        "INSERT INTO certification_report (week_ending, version, state, profile_json,"
        " entries_json, alternates_json, gaps_json, generated_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            week_ending, version, profile.get("state", ""), json.dumps(profile),
            json.dumps(entries), json.dumps(alternates), json.dumps(gaps), _now(),
        ),
    )
    return cur.lastrowid, version


def _load_report(con, report_id: int) -> "dict | None":
    row = con.execute(
        "SELECT * FROM certification_report WHERE id = ?", (int(report_id),)
    ).fetchone()
    if row is None:
        return None
    report = dict(row)
    for key in ("profile_json", "entries_json", "alternates_json", "gaps_json", "exports_json"):
        try:
            report[key[:-5]] = json.loads(report.get(key) or ("{}" if key == "profile_json" else "[]"))
        except (TypeError, ValueError):
            report[key[:-5]] = {} if key == "profile_json" else []
    return report


def _format_entry(i: int, entry: dict) -> str:
    lines = [
        f"  {i}. {entry['employer']} — {entry['position'] or '(position not recorded)'}",
        f"     {entry['date']} · {entry['method']}"
        + (f" · contact: {entry['contact']}" if entry.get("contact") else ""),
        f"     address: {entry['address'] or '⚠ NEEDS ADDRESS — certification(action=\"employer_override\", ...)'}",
    ]
    if entry.get("website"):
        lines.append(f"     website: {entry['website']}")
    lines.append(f"     result: {entry['result']}  [{entry['kind']}]")
    lines.append(f"     sources: {', '.join(entry['source_event_ids'])}")
    return "\n".join(lines)


def weekly_certification_report(week_ending: str = "") -> str:
    """Derive, enrich, rank, and freeze this week's certification report.

    Entries trace to logged events only. Under-target weeks are reported
    loudly — the tool never pads. Regeneration creates a new version;
    prior versions are retained.
    """
    profile = get_state_profile()
    end = _week_ending_date(profile, week_ending)
    if isinstance(end, str):
        return end
    start, end_date = _week_window(end)
    target = int(profile.get("min_activities_per_week", 3))

    activities = derive_activities(start, end_date, profile)
    picked, alternates = select_entries(activities, target)

    entries: list[dict] = []
    gaps: list[str] = []
    for activity in picked:
        try:
            row = enrich_employer(
                activity["employer"],
                website_hint=activity.get("website_hint", ""),
            )
        except Exception:  # noqa: BLE001 — enrichment failure ≠ report failure
            row = {"canonical_name": employer_of_record(activity["employer"]), "aliases": []}
        entry = _entry_payload(activity, row)
        if entry.get("needs_address"):
            gaps.append(f"{entry['employer']}: no verifiable business address (needs_address)")
        entries.append(entry)
    alternate_entries = [
        {k: a[k] for k in ("kind", "employer", "position", "date", "method", "contact", "result", "source_event_ids")}
        for a in alternates
    ]
    if len(entries) < target:
        gaps.insert(
            0,
            f"UNDER TARGET: {len(entries)} qualifying activit{'y' if len(entries) == 1 else 'ies'} "
            f"logged this week — {profile['state']} requires {target}. "
            "The report is NOT padded; log real activities and regenerate.",
        )

    with get_connection() as con:
        report_id, version = _insert_report(
            con, end_date.isoformat(), profile, entries, alternate_entries, gaps
        )
    _audit_append({
        "report_id": report_id,
        "week_ending": end_date.isoformat(),
        "version": version,
        "state": profile.get("state", ""),
        "entries": entries,
        "gaps": gaps,
        "generated_at": _now(),
    })

    status = "✓" if len(entries) >= target and not gaps else "⚠"
    lines = [
        f"═══ CERTIFICATION WEEK {start.isoformat()} → {end_date.isoformat()} "
        f"({profile['state']}) — report #{report_id} v{version} ═══",
        f"{status} {len(entries)}/{target} required activities",
        "",
    ]
    lines += [_format_entry(i + 1, e) for i, e in enumerate(entries)] or ["  (no qualifying activities)"]
    if gaps:
        lines += ["", "GAPS:"] + [f"  ⚠ {g}" for g in gaps]
    if alternate_entries:
        lines += ["", f"ALTERNATES ({len(alternate_entries)} — swap before export with "
                      "certification(action=\"swap_entry\", ...)):"]
        lines += [
            f"  {chr(97 + i)}. {a['employer']} — {a['kind']} on {a['date']}"
            for i, a in enumerate(alternate_entries)
        ]
    return "\n".join(lines)


def list_certification_reports(limit: int = 10) -> str:
    """History of frozen weekly reports, newest first."""
    with get_connection() as con:
        rows = con.execute(
            "SELECT id, week_ending, version, state, entries_json, gaps_json, generated_at"
            " FROM certification_report ORDER BY week_ending DESC, version DESC LIMIT ?",
            (max(1, int(limit)),),
        ).fetchall()
    if not rows:
        return (
            "No certification reports yet. Generate the current week with "
            "certification(action=\"weekly_report\")."
        )
    lines = ["═══ CERTIFICATION REPORTS ═══"]
    for row in rows:
        try:
            n_entries = len(json.loads(row["entries_json"] or "[]"))
            n_gaps = len(json.loads(row["gaps_json"] or "[]"))
        except (TypeError, ValueError):
            n_entries, n_gaps = 0, 0
        flag = f" · ⚠ {n_gaps} gap(s)" if n_gaps else ""
        lines.append(
            f"  #{row['id']} — week ending {row['week_ending']} v{row['version']}"
            f" ({row['state']}) · {n_entries} entries{flag} · generated {row['generated_at']}"
        )
    return "\n".join(lines)


def swap_certification_entry(report_id: int, out_entry: int, in_entry: str = "") -> str:
    """Replace entry #out_entry with an alternate (by letter, e.g. "a").

    Reports are immutable — the swap freezes a NEW version; the prior
    version is retained for the audit trail.
    """
    with get_connection() as con:
        report = _load_report(con, report_id)
    if report is None:
        return f"✗ No certification report with id={report_id}."
    entries = report["entries"]
    alternates = report["alternates"]
    if not 1 <= int(out_entry) <= len(entries):
        return f"✗ out_entry must be 1–{len(entries)}."
    key = str(in_entry or "").strip().lower()
    idx = ord(key) - 97 if len(key) == 1 and key.isalpha() else -1
    if not 0 <= idx < len(alternates):
        return f"✗ in_entry must be an alternate letter a–{chr(96 + len(alternates))}." if alternates \
            else "✗ This report has no alternates to swap in."
    incoming = alternates[idx]
    try:
        row = enrich_employer(incoming["employer"])
    except Exception:  # noqa: BLE001
        row = {"canonical_name": employer_of_record(incoming["employer"]), "aliases": []}
    new_entries = list(entries)
    outgoing = new_entries[int(out_entry) - 1]
    new_entries[int(out_entry) - 1] = _entry_payload({**incoming, "strength": 9}, row)
    new_alternates = [a for i, a in enumerate(alternates) if i != idx]
    new_alternates.append({k: outgoing[k] for k in (
        "kind", "employer", "position", "date", "method", "contact", "result", "source_event_ids"
    )})
    gaps = [g for g in report["gaps"] if not g.startswith(outgoing["employer"])]
    if new_entries[int(out_entry) - 1].get("needs_address"):
        gaps.append(f"{incoming['employer']}: no verifiable business address (needs_address)")
    with get_connection() as con:
        new_id, version = _insert_report(
            con, report["week_ending"], report["profile"], new_entries, new_alternates, gaps
        )
    _audit_append({
        "report_id": new_id,
        "week_ending": report["week_ending"],
        "version": version,
        "swap": {"from_report": int(report_id), "out": outgoing["employer"], "in": incoming["employer"]},
        "generated_at": _now(),
    })
    return (
        f"✓ Swapped out #{out_entry} ({outgoing['employer']}) for {incoming['employer']}. "
        f"New frozen report #{new_id} v{version}; #{report_id} retained."
    )


# ── Export ────────────────────────────────────────────────────────────────────

_EXPORT_FORMATS = ("csv", "portal_text", "pdf", "docx")


def export_certification_report(
    report_id: int,
    format: Literal["csv", "portal_text", "pdf", "docx"] = "portal_text",
) -> str:
    """Render a frozen report for the claim portal.

    Truth gate (same posture as generation): every entry must carry at least
    one source event id — export is blocked otherwise.
    """
    fmt = str(format or "").strip().lower()
    if fmt not in _EXPORT_FORMATS:
        return f"✗ format must be one of: {', '.join(_EXPORT_FORMATS)}."
    with get_connection() as con:
        report = _load_report(con, report_id)
    if report is None:
        return f"✗ No certification report with id={report_id}."

    untraced = [
        e["employer"] for e in report["entries"] if not e.get("source_event_ids")
    ]
    if untraced:
        return (
            "✗ EXPORT BLOCKED — entries without a source event: "
            f"{', '.join(untraced)}. Certification entries must trace to "
            "logged events; regenerate the report."
        )
    if not report["entries"]:
        return "✗ EXPORT BLOCKED — the report has no entries."

    if fmt in ("pdf", "docx"):
        return (
            f"✗ {fmt} export isn't wired yet (v1 ships csv + portal_text; "
            "use the dashboard's print view for paper)."
        )

    profile = report["profile"]
    required = profile.get("required_fields", DEFAULT_STATE_PROFILE["required_fields"])
    if fmt == "csv":
        buf = io.StringIO()
        writer = csv.writer(buf, lineterminator="\n")
        writer.writerow([
            "employer", "business_address", "website", "position", "date",
            "contact_method", "contact_name", "result",
        ])
        for e in report["entries"]:
            writer.writerow([
                e["employer"], e["address"], e["website"], e["position"],
                e["date"], e["method"], e["contact"], e["result"],
            ])
        rendered = buf.getvalue()
    else:  # portal_text — plain lines for copy-paste into the claim portal
        blocks = []
        for i, e in enumerate(report["entries"], 1):
            blocks.append("\n".join([
                f"Activity {i}",
                f"Employer: {e['employer']}",
                f"Business address: {e['address'] or 'NEEDS ADDRESS'}",
                f"Website: {e['website'] or '-'}",
                f"Position: {e['position'] or '-'}",
                f"Date of contact: {e['date']}",
                f"Method of contact: {e['method']}",
                f"Contact: {e['contact'] or '-'}",
                f"Result: {e['result']}",
            ]))
        rendered = "\n\n".join(blocks)

    missing = [
        e["employer"] for e in report["entries"]
        if "address" in required and not e.get("address")
    ]
    with get_connection() as con:
        con.execute(
            "UPDATE certification_report SET exports_json = json_insert(exports_json,"
            " '$[#]', json(?)) WHERE id = ?",
            (json.dumps({"format": fmt, "at": _now()}), int(report_id)),
        )
    header = (
        f"═══ EXPORT — report #{report_id} (week ending {report['week_ending']},"
        f" {fmt}) ═══\n"
    )
    warning = (
        f"⚠ Missing required address for: {', '.join(missing)} — fix with "
        "certification(action=\"employer_override\", ...) then re-export.\n\n"
        if missing else ""
    )
    return header + warning + rendered


# ── Registration ──────────────────────────────────────────────────────────────

def register(mcp) -> None:
    mcp.tool()(weekly_certification_report)
    mcp.tool()(list_certification_reports)
    mcp.tool()(export_certification_report)
    mcp.tool()(swap_certification_entry)
    mcp.tool()(lookup_employer)
    mcp.tool()(override_employer)
    mcp.tool()(certification_state_profile)
