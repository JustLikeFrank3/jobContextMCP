"""
Compensation comparison tool — v4

Stores comp data (base, equity, bonus, level, location) per application
and produces a side-by-side comparison table.

Tools:
  update_compensation          — add/update comp details for a tracked application
  get_compensation_comparison  — side-by-side table of all tracked comp data
"""

from lib import config
from lib.io import _load_json, _save_json, _now


def update_compensation(
    company: str,
    role: str,
    base: int = 0,
    equity_total: int = 0,
    equity_vest_years: int = 4,
    bonus_target_pct: float = 0.0,
    level: str = "",
    location: str = "",
    remote: bool = False,
    notes: str = "",
) -> str:
    """
    Add or update compensation details for a tracked job application.

    Figures are stored per company+role in the status.json comp block.
    If the application isn't tracked yet this will create a placeholder entry.

    Args:
        company:            Company name (must match an existing application, or creates new).
        role:               Role title.
        base:               Annual base salary in USD (e.g. 180000).
        equity_total:       Total equity grant in USD (e.g. 200000 for $200K over 4 years).
        equity_vest_years:  Vesting period in years (default 4).
        bonus_target_pct:   Target bonus as a percentage of base (e.g. 15 for 15%).
        level:              Job level / title at this company (e.g. 'SWE II', 'L5').
        location:           Office location (e.g. 'Seattle, WA', 'Remote').
        remote:             True if fully remote.
        notes:              Any comp-specific notes (signing bonus, cliff, etc.).

    Returns:
        Confirmation string with computed total compensation estimate.
    """
    data = _load_json(config.STATUS_FILE, {"applications": []})
    apps: list = data.setdefault("applications", [])

    existing = next(
        (a for a in apps if a["company"].lower() == company.lower() and a["role"].lower() == role.lower()),
        None,
    )
    if existing is None:
        existing = next((a for a in apps if a["company"].lower() == company.lower()), None)

    if existing is None:
        existing = {
            "company": company,
            "role": role,
            "status": "tracking",
            "applied_date": _now(),
            "last_updated": _now(),
        }
        apps.append(existing)

    annual_equity = (equity_total / equity_vest_years) if equity_vest_years > 0 else 0
    bonus_amount = int(base * bonus_target_pct / 100) if base and bonus_target_pct else 0
    total_comp = base + annual_equity + bonus_amount

    existing["comp"] = {
        "base": base,
        "equity_total": equity_total,
        "equity_vest_years": equity_vest_years,
        "equity_annual": round(annual_equity),
        "bonus_target_pct": bonus_target_pct,
        "bonus_amount": bonus_amount,
        "level": level,
        "location": location,
        "remote": remote,
        "notes": notes,
        "total_comp_estimate": round(total_comp),
        "updated_at": _now(),
    }
    existing["last_updated"] = _now()

    data["last_updated"] = _now()
    _save_json(config.STATUS_FILE, data)

    return (
        f"✓ Comp updated: {company} — {role}\n"
        f"  Base: ${base:,}  |  Equity: ${equity_total:,} over {equity_vest_years}yr  |  "
        f"Bonus target: {bonus_target_pct}%\n"
        f"  Estimated total comp: ${round(total_comp):,}/yr"
    )


def get_compensation_comparison() -> str:
    """
    Return a side-by-side compensation comparison table for all tracked applications
    that have comp data entered via update_compensation().

    Includes: company, role, level, base, annual equity, bonus, estimated total comp,
    location/remote status, and any notes. Sorted by total comp estimate descending.

    Returns:
        Formatted comparison table string. Returns guidance if no comp data exists yet.
    """
    data = _load_json(config.STATUS_FILE, {"applications": []})
    apps = data.get("applications", [])

    with_comp = [a for a in apps if a.get("comp")]

    if not with_comp:
        return (
            "No compensation data tracked yet.\n"
            "Use update_compensation(company, role, base=...) to add comp details."
        )

    with_comp.sort(key=lambda a: a["comp"].get("total_comp_estimate", 0), reverse=True)

    # Column header
    lines = [
        "═══ COMPENSATION COMPARISON ═══",
        "",
        f"{'Company':<18} {'Role':<30} {'Level':<8} {'Base':>10} {'Eq/yr':>10} {'Bonus':>8} {'Total':>12}  Location",
        "─" * 110,
    ]

    for a in with_comp:
        c = a["comp"]
        company = a.get("company", "?")[:17]
        role = a.get("role", "?")[:29]
        level = c.get("level", "")[:7]
        base = f"${c.get('base', 0):,}" if c.get("base") else "—"
        eq_yr = f"${c.get('equity_annual', 0):,}" if c.get("equity_annual") else "—"
        bonus = f"${c.get('bonus_amount', 0):,}" if c.get("bonus_amount") else "—"
        total = f"${c.get('total_comp_estimate', 0):,}" if c.get("total_comp_estimate") else "—"
        remote_tag = " (remote)" if c.get("remote") else ""
        loc = (c.get("location", "") + remote_tag)[:20]

        lines.append(
            f"{company:<18} {role:<30} {level:<8} {base:>10} {eq_yr:>10} {bonus:>8} {total:>12}  {loc}"
        )
        if c.get("notes"):
            lines.append(f"  {'':18} ↳ {c['notes']}")

    lines += [
        "─" * 110,
        "",
        f"Tracking {len(with_comp)} offer{'s' if len(with_comp) != 1 else ''} / package{'s' if len(with_comp) != 1 else ''}.",
    ]

    # Highlight best total
    best = with_comp[0]
    lines.append(
        f"Highest total comp: {best['company']} — ${best['comp'].get('total_comp_estimate', 0):,}/yr"
    )

    return "\n".join(lines)


def register(mcp) -> None:
    mcp.tool()(update_compensation)
    mcp.tool()(get_compensation_comparison)
