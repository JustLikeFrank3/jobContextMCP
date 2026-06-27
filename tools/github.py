"""
GitHub stats tool — F1 feature track.

`get_github_stats(username)` pulls a lightweight public profile summary from
the GitHub REST API (`/users/{user}` + `/users/{user}/repos`) and returns a
formatted text block suitable for inclusion in cover letters, resumes, or
recruiter outreach.

Network and credentials:
    * Reads token from env `GITHUB_TOKEN` if set (raises rate limit to 5000/h);
      otherwise calls the unauthenticated public endpoint (60/h).
    * If env `JOBCONTEXTMCP_OFFLINE=1`, returns a deterministic offline stub
      without making any network call. Tests use this.
    * Network errors degrade gracefully to a "⚠ unable to fetch" message
      rather than raising.

The implementation uses urllib from the stdlib so no new dependency is added.
"""

from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from typing import Any


_GITHUB_API = "https://api.github.com"


def _open_https(req: "urllib.request.Request", timeout: float):
    """Open an HTTPS request, rejecting any non-HTTPS scheme.

    All callers build URLs from the ``_GITHUB_API`` constant, so the scheme is
    always ``https``. This explicit guard prevents a ``file:``/custom-scheme URL
    from ever reaching ``urlopen`` and satisfies static analysers (B310 / SSRF).
    """
    if req.type != "https":
        raise ValueError(f"refusing non-HTTPS request scheme: {req.type!r}")
    return urllib.request.urlopen(req, timeout=timeout)  # nosec B310 - scheme checked above


def _is_offline() -> bool:
    return os.environ.get("JOBCONTEXTMCP_OFFLINE", "").lower() in ("1", "true", "yes")


def _http_get_json(url: str, timeout: float = 5.0) -> Any:
    """Fetch JSON from a URL. Raises urllib.error.URLError on network problems."""
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "jobContextMCP-github-stats/1.0",
    }
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with _open_https(req, timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _offline_stub(username: str) -> dict[str, Any]:
    return {
        "profile": {
            "login": username,
            "name": "Offline Stub",
            "bio": "Offline mode active — set JOBCONTEXTMCP_OFFLINE=0 to fetch live.",
            "public_repos": 0,
            "followers": 0,
            "following": 0,
            "html_url": f"https://github.com/{username}",
        },
        "top_repos": [],
    }


def _fetch(username: str) -> dict[str, Any]:
    if _is_offline():
        return _offline_stub(username)
    try:
        profile = _http_get_json(f"{_GITHUB_API}/users/{username}")
        repos = _http_get_json(
            f"{_GITHUB_API}/users/{username}/repos?per_page=100&sort=updated"
        )
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {
            "profile": None,
            "top_repos": [],
            "error": f"unable to fetch GitHub data for {username}: {exc}",
        }

    # Trim profile + repo fields to what we display.
    prof = {
        "login": profile.get("login"),
        "name": profile.get("name"),
        "bio": profile.get("bio"),
        "public_repos": profile.get("public_repos", 0),
        "followers": profile.get("followers", 0),
        "following": profile.get("following", 0),
        "html_url": profile.get("html_url"),
    }
    top = sorted(
        [r for r in repos if not r.get("fork")],
        key=lambda r: r.get("stargazers_count", 0),
        reverse=True,
    )[:5]
    top_repos = [
        {
            "name": r.get("name"),
            "description": r.get("description") or "",
            "language": r.get("language") or "",
            "stars": r.get("stargazers_count", 0),
            "url": r.get("html_url"),
        }
        for r in top
    ]
    return {"profile": prof, "top_repos": top_repos}


def get_github_stats(username: str) -> str:
    """Return a formatted GitHub public profile summary.

    Args:
        username: GitHub login (e.g. "JustLikeFrank3").

    Returns:
        Multi-line text block. Includes a "⚠" prefix line on fetch failure.
    """
    if not username or not username.strip():
        return "⚠ get_github_stats: username is required"
    username = username.strip()

    data = _fetch(username)
    if data.get("error"):
        return f"⚠ {data['error']}"

    prof = data["profile"] or {}
    lines = [
        f"# GitHub profile: @{prof.get('login', username)}",
        prof.get("name") or "(no display name)",
        prof.get("bio") or "(no bio)",
        "",
        f"Public repos: {prof.get('public_repos', 0)}    "
        f"Followers: {prof.get('followers', 0)}    "
        f"Following: {prof.get('following', 0)}",
        f"URL: {prof.get('html_url', f'https://github.com/{username}')}",
    ]
    repos = data.get("top_repos", [])
    if repos:
        lines.append("")
        lines.append("## Top non-fork repos (by stars, recently updated)")
        for r in repos:
            lang = f" [{r['language']}]" if r.get("language") else ""
            stars = f" ★{r['stars']}" if r.get("stars") else ""
            desc = f" — {r['description']}" if r.get("description") else ""
            lines.append(f"- {r['name']}{lang}{stars}{desc}")
            lines.append(f"  {r['url']}")
    return "\n".join(lines)


# ── Portfolio traffic metrics (clones / views) with permanent local history ──
#
# GitHub's traffic API only retains a trailing 14-day window. To build a
# durable, defensible cumulative number we snapshot every refresh into a local
# history file (config.GITHUB_METRICS_FILE), merging daily buckets so days are
# never lost once they scroll out of GitHub's window.
#
# Auth: the traffic endpoints require push access. We resolve a token from, in
# order: env GITHUB_TOKEN, then the `gh` CLI keyring (`gh auth token`). The
# token is never written to disk.


def _resolve_token() -> str | None:
    """Resolve a GitHub token: env GITHUB_TOKEN first, then `gh auth token`."""
    env = os.environ.get("GITHUB_TOKEN")
    if env:
        return env.strip()
    try:
        result = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            tok = result.stdout.strip()
            return tok or None
    except (subprocess.TimeoutExpired, OSError):
        return None
    return None


def _full_slug(repo: str, username: str) -> str:
    """Normalize a repo entry to an 'owner/name' slug."""
    repo = repo.strip()
    if "/" in repo:
        return repo
    return f"{username}/{repo}" if username else repo


def _fetch_traffic(slug: str, kind: str, token: str) -> dict[str, Any] | None:
    """Fetch /traffic/{clones|views} for a repo slug. Returns parsed JSON or None."""
    url = f"{_GITHUB_API}/repos/{slug}/traffic/{kind}"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "jobContextMCP-portfolio-metrics/1.0",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with _open_https(req, 10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (OSError, ValueError):
        return None


def _metrics_path():
    from lib import config

    return config.GITHUB_METRICS_FILE


def _load_history() -> dict[str, Any]:
    path = _metrics_path()
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            pass
    return {"tracking_since": None, "last_refreshed": None, "repos": {}}


def _save_history(data: dict[str, Any]) -> None:
    path = _metrics_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")  # noqa: S5145


def _merge_buckets(existing: dict[str, Any], payload: dict[str, Any], key: str) -> None:
    """Merge a traffic payload's daily buckets into existing[key] by date.

    Past daily counts are stable once the day closes, so overwriting is safe and
    keeps today's count fresh. Old days outside GitHub's 14-day window are
    retained because they already live in `existing`.
    """
    daily = existing.setdefault(key, {})
    for bucket in payload.get(key, []):
        ts = bucket.get("timestamp", "")[:10]  # YYYY-MM-DD
        if not ts:
            continue
        daily[ts] = {
            "count": int(bucket.get("count", 0)),
            "uniques": int(bucket.get("uniques", 0)),
        }


def _window_sum(daily: dict[str, dict], days: int) -> tuple[int, int]:
    """Sum count and uniques over the trailing `days` calendar days from today."""
    cutoff = date.today() - timedelta(days=days - 1)
    total_count = 0
    total_uniques = 0
    for ds, vals in daily.items():
        try:
            d = date.fromisoformat(ds)
        except ValueError:
            continue
        if d >= cutoff:
            total_count += int(vals.get("count", 0))
            total_uniques += int(vals.get("uniques", 0))
    return total_count, total_uniques


def _cumulative(daily: dict[str, dict]) -> int:
    """Sum of all recorded daily counts (the durable cumulative-observed total)."""
    return sum(int(v.get("count", 0)) for v in daily.values())


def _refresh_one(slug: str, token: str, repos_hist: dict[str, Any]) -> bool:
    """Fetch + merge traffic for a single repo. Returns True on any data."""
    clones = _fetch_traffic(slug, "clones", token)
    views = _fetch_traffic(slug, "views", token)
    if clones is None and views is None:
        return False
    entry = repos_hist.setdefault(slug, {})
    if clones is not None:
        _merge_buckets(entry, clones, "clones")
    if views is not None:
        _merge_buckets(entry, views, "views")
    return True


def _summary_line(slug: str, entry: dict[str, Any]) -> str:
    clones_daily = entry.get("clones", {})
    c14, u14 = _window_sum(clones_daily, 14)
    cum = _cumulative(clones_daily)
    ndays = len(clones_daily)
    return (
        f"✓ {slug}: {c14} clones / {u14} unique (last 14d) · "
        f"{cum} clones cumulative-observed over {ndays} tracked days"
    )


def refresh_portfolio_metrics() -> str:
    """Pull live GitHub clone + view traffic for all configured repos and merge
    into the permanent local history file.

    GitHub only retains a trailing 14-day traffic window; this snapshots each
    refresh so days are never lost. Reports per-repo trailing-14-day rate plus
    the growing cumulative-observed total. Run it any time — weekly, or per
    application batch. It never drops previously recorded days.

    Auth uses env GITHUB_TOKEN or the `gh` CLI keyring; no secret is stored.

    Returns:
        A formatted summary of what was refreshed.
    """
    from lib import config

    cfg = config.get_github_metrics_config()
    username = cfg.get("username", "")
    repos = cfg.get("repos", [])
    if not repos:
        return "⚠ refresh_portfolio_metrics: no repos configured (config.github_metrics.repos is empty)"

    token = _resolve_token()
    if not token:
        return (
            "⚠ refresh_portfolio_metrics: no GitHub token available.\n"
            "Set env GITHUB_TOKEN, or authenticate the GitHub CLI (`gh auth login`).\n"
            "The traffic API requires push access to each repo."
        )

    history = _load_history()
    repos_hist = history.setdefault("repos", {})
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    refreshed: list[str] = []
    failed: list[str] = []
    for repo in repos:
        slug = _full_slug(repo, username)
        if _refresh_one(slug, token, repos_hist):
            refreshed.append(slug)
        else:
            failed.append(slug)

    # tracking_since = earliest clone date across all repos we have data for.
    all_clone_dates: list[str] = []
    for entry in repos_hist.values():
        all_clone_dates.extend(entry.get("clones", {}).keys())
    if all_clone_dates:
        history["tracking_since"] = min(all_clone_dates)
    history["last_refreshed"] = now
    _save_history(history)

    lines = [f"# Portfolio metrics refreshed — {now}"]
    if history.get("tracking_since"):
        lines.append(f"Tracking since: {history['tracking_since']}")
    lines.append("")
    lines.extend(_summary_line(slug, repos_hist[slug]) for slug in refreshed)
    if failed:
        lines.append("")
        lines.extend(
            f"⚠ {slug}: traffic unavailable (no push access or repo not found)"
            for slug in failed
        )
    return "\n".join(lines)


def get_portfolio_metrics() -> str:
    """Return a resume/STAR-ready summary of GitHub portfolio traffic.

    Reads the local history file written by refresh_portfolio_metrics(). Reports,
    per repo and in aggregate: the trailing-14-day clone rate (live momentum) and
    the cumulative-observed clone total since tracking began (a durable number
    that only grows). Run refresh_portfolio_metrics() first to populate/update.

    Returns:
        Multi-line text block. Safe to paste into context, cover letters, or
        recruiter messages. Each figure is sourced to GitHub traffic data.
    """
    history = _load_history()
    repos_hist = history.get("repos", {})
    if not repos_hist:
        return (
            "No portfolio metrics recorded yet. "
            "Run refresh_portfolio_metrics() to pull live GitHub traffic."
        )

    since = history.get("tracking_since") or "unknown"
    last = history.get("last_refreshed") or "never"
    lines = [
        "# GitHub portfolio traffic",
        f"Tracking since {since} · last refreshed {last}",
        "(Source: GitHub traffic API. 14-day window is GitHub's live rate; "
        "cumulative is the durable total observed since tracking began.)",
        "",
    ]

    total_c14 = total_u14 = total_cum = 0
    rows: list[tuple[str, int, int, int, int]] = []
    for slug, entry in repos_hist.items():
        clones_daily = entry.get("clones", {})
        c14, u14 = _window_sum(clones_daily, 14)
        cum = _cumulative(clones_daily)
        ndays = len(clones_daily)
        rows.append((slug, c14, u14, cum, ndays))
        total_c14 += c14
        total_u14 += u14
        total_cum += cum

    rows.sort(key=lambda r: r[3], reverse=True)
    for slug, c14, u14, cum, ndays in rows:
        name = slug.split("/", 1)[-1]
        lines.append(
            f"• {name}: {c14} clones / {u14} unique (last 14d) · "
            f"{cum} cumulative over {ndays} tracked days"
        )
    lines.append("")
    lines.append(
        f"TOTAL across {len(rows)} repos: {total_c14} clones / {total_u14} unique "
        f"in the last 14 days · {total_cum} clones cumulative-observed."
    )
    return "\n".join(lines)


def register(mcp) -> None:
    mcp.tool()(get_github_stats)
    mcp.tool()(refresh_portfolio_metrics)
    mcp.tool()(get_portfolio_metrics)
