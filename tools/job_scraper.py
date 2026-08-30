"""
job_scraper — Web-based job ingestion.

Entry points:

  scrape_job_url         — Fetch a single posting URL and extract the content.
                           Uses Jina Reader (r.jina.ai) — no extra dependencies.
                           Works on Greenhouse, Lever, Ashby, Workday, and most
                           company career pages.  LinkedIn is not reliable.

  search_jobs            — Search Google Jobs via SerpAPI (requires serpapi_key).

  search_greenhouse_jobs — Browse all open roles on a company's Greenhouse board.
                           Free, no API key.  Works for any company on Greenhouse.

  search_lever_jobs      — Browse all open roles on a company's Lever board.
                           Free, no API key.  Works for any company on Lever.

All four accept auto_queue=True to pass results through queue_job into the
existing evaluation pipeline.
"""

import html as _html_mod
import json as _json
import re
from urllib.parse import urlparse

import httpx

from lib import config
from tools.job_queue import queue_job as _queue_job


# ── Exceptions ────────────────────────────────────────────────────────────────

class LinkedInBlockedError(Exception):
    """Raised when a LinkedIn URL can't be scraped.

    LinkedIn returns HTTP 451 (Unavailable For Legal Reasons) to Jina Reader,
    and its /jobs/view pages are usually behind a login wall for full JD
    content.  Both the MCP scrape_job_url tool and the HTTP /jobs/ingest-url
    route catch this so they can return a human-readable fallback message
    rather than a generic HTTP error.
    """

    def __init__(self, url: str) -> None:
        self.url = url
        super().__init__(
            f"LinkedIn blocks automated scraping for {url}. "
            "Open the posting, copy the full job description text, "
            "and paste it into Dashboard → Pipeline → Add Job."
        )


# ── Constants ─────────────────────────────────────────────────────────────────

_JINA_BASE         = "https://r.jina.ai/"
_SERPAPI_BASE      = "https://serpapi.com/search.json"
_GREENHOUSE_BASE   = "https://boards-api.greenhouse.io/v1/boards"
_LEVER_BASE        = "https://api.lever.co/v0/postings"
_HTTP_TIMEOUT      = 20  # seconds
_UNKNOWN_ROLE      = "Unknown Role"
_AUTO_QUEUED_HEADER = "─── AUTO-QUEUED ───"
_SCRAPE_JOB_URL_TIP = (
    "Tip: call scrape_job_url(link) on any listing above to fetch the full JD "
    "and queue it for fitment review."
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _strip_html(raw: str) -> str:
    """Strip HTML tags and unescape entities to plain text."""
    text = re.sub(r"<[^>]+>", " ", raw)
    text = _html_mod.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _is_linkedin_url(url: str) -> bool:
    """Return True if *url* is a LinkedIn URL."""
    return "linkedin.com" in (urlparse(url).hostname or "").lower()


def _fetch_linkedin_direct(url: str) -> str:  # NOSONAR
    """Attempt a direct fetch of a LinkedIn job page via JSON-LD / Open Graph.

    LinkedIn blocks Jina (HTTP 451) but public job postings often include
    server-rendered JSON-LD ``JobPosting`` blocks and ``og:`` meta tags that
    are visible to a browser User-Agent without login.  Returns extracted
    plain text on success, or an empty string if the page is gated/empty.
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        resp = httpx.get(url, headers=headers, timeout=_HTTP_TIMEOUT, follow_redirects=True)
        if resp.status_code != 200:
            return ""
        html = resp.text

        # ── JSON-LD JobPosting (richest source) ───────────────────────────────
        for ld_raw in re.findall(
            r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',  # NOSONAR — scraping internal HTML, not raw user HTTP input
            html,
            re.DOTALL | re.IGNORECASE,
        ):
            try:
                ld = _json.loads(ld_raw)
                # Handle top-level array or @graph
                nodes = ld if isinstance(ld, list) else ld.get("@graph", [ld])
                for node in nodes:
                    if not isinstance(node, dict):
                        continue
                    if (node.get("@type") or "").strip().lower() != "jobposting":
                        continue
                    title = str(node.get("title") or "").strip()
                    desc = _strip_html(str(node.get("description") or ""))
                    company = ""
                    org = node.get("hiringOrganization") or {}
                    if isinstance(org, dict):
                        company = str(org.get("name") or "").strip()
                    parts: list[str] = []
                    if title:
                        parts.append(f"# {title}")
                    if company:
                        parts.append(f"at {company}")
                    if desc:
                        parts.append(desc)
                    combined = "\n\n".join(parts)
                    if len(combined) > 100:  # sanity check: real content present
                        return combined
            except Exception:
                continue

        # LinkedIn og: tags are unreliable — after URL expiry or a redirect,
        # LinkedIn serves a jobs-search page whose og:description is something
        # like "Today's top N jobs at Company…" rather than the actual JD.
        # Skip the og: fallback for LinkedIn; only trust JSON-LD JobPosting.
    except Exception:
        pass
    return ""


def _fetch_linkedin_guest(url: str) -> str:
    """Fallback: LinkedIn's public jobs-guest fragment endpoint.

    /jobs-guest/jobs/api/jobPosting/{id} serves a server-rendered HTML
    fragment of the posting without login and is less aggressively gated for
    datacenter IPs than the full page (which often serves an authwall with no
    JSON-LD from cloud egress). Returns plain text or "".
    """
    m = re.search(r"/jobs/view/(\d+)", url) or re.search(r"currentJobId=(\d+)", url)
    if not m:
        return ""
    guest_url = f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{m.group(1)}"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        resp = httpx.get(guest_url, headers=headers, timeout=_HTTP_TIMEOUT, follow_redirects=True)
        if resp.status_code != 200:
            return ""
        # LinkedIn HTML wraps attributes across lines — normalize before any
        # tag-level regex work.
        html = re.sub(r"\s+", " ", resp.text)
        # Extract the title from its dedicated element. No title element ⇒
        # authwall/expired/interstitial — refuse rather than import junk
        # (a nonexistent job id still returns 200 with a decorative page).
        m_title = re.search(
            r"<h2[^>]*(?:top-card|title)[^>]*>(.*?)</h2>", html, re.IGNORECASE)
        title = _strip_html(m_title.group(1)).strip() if m_title else ""
        if not title:
            return ""
        m_org = re.search(
            r"<a[^>]*org-name[^>]*>(.*?)</a>|<h4[^>]*>(.*?)</h4>", html, re.IGNORECASE)
        company = ""
        if m_org:
            company = _strip_html(m_org.group(1) or m_org.group(2) or "").strip()
            company = re.sub(r"^at\s+", "", company)
        body = _strip_html(html)
        parts = [f"# {title}"]
        if company:
            parts.append(f"at {company}")
        parts.append(body[:8000])
        text = "\n\n".join(parts)
        return text if len(text) > 100 else ""
    except Exception:
        return ""


def _fetch_jina(url: str) -> str:
    """Return cleaned markdown text for *url* via Jina Reader.

    For LinkedIn URLs: Jina returns HTTP 451 (blocked for legal reasons).
    Attempts a direct browser-UA fetch first (JSON-LD / og: tags).  Raises
    :exc:`LinkedInBlockedError` if no usable content can be extracted.
    """
    if _is_linkedin_url(url):
        fallback = _fetch_linkedin_direct(url) or _fetch_linkedin_guest(url)
        if fallback.strip():
            return fallback
        raise LinkedInBlockedError(url)

    response = httpx.get(
        f"{_JINA_BASE}{url}",
        headers={"Accept": "text/plain"},
        timeout=_HTTP_TIMEOUT,
        follow_redirects=True,
    )
    # Jina sometimes returns 4xx with a full body (e.g. Coca-Cola careers returns
    # 400 but the complete JD is in the response text). Only raise if the body is
    # empty — otherwise use whatever content we got.
    if not response.text.strip():
        response.raise_for_status()
    return response.text


def _company_from_url(url: str) -> str:
    """Best-effort company name derived from the URL hostname."""
    host = urlparse(url).hostname or ""
    # Strip common job-board prefixes so we surface the company name
    host = re.sub(
        r"^(www\.|jobs\.|careers\.|apply\.|boards\.greenhouse\.io/|lever\.co/)",
        "",
        host,
    )
    name = host.split(".")[0]
    return name.replace("-", " ").title()


def _normalize_title_metadata(role: str, company: str, url: str) -> tuple[str, str]:
    """Clean aggregator-style titles, especially LinkedIn share pages."""
    cleaned_role = re.sub(r"^\s*title:\s*", "", role or "", flags=re.IGNORECASE).strip()
    cleaned_role = re.sub(r"\s*\|\s*linkedin\s*$", "", cleaned_role, flags=re.IGNORECASE).strip()  # NOSONAR — internal text cleanup, trusted input

    host = (urlparse(url).hostname or "").lower()
    if "linkedin." in host:
        m = re.match(r"^(?P<company>.+?)\s+hiring\s+(?P<role>.+)$", cleaned_role, flags=re.IGNORECASE)  # NOSONAR — internal text cleanup, trusted input
        if m:
            title_company = re.sub(r"\s+", " ", m.group("company")).strip(" ,|-")
            title_role = re.sub(r"\s+", " ", m.group("role")).strip(" ,|-")
            if title_company:
                company = title_company
            cleaned_role = title_role

        cleaned_role = re.sub(r"\s+in\s+[A-Z][A-Za-z .'-]+,\s*[A-Z]{2}\s*$", "", cleaned_role).strip()  # NOSONAR — internal text cleanup, trusted input

    cleaned_role = re.sub(r"\s+", " ", cleaned_role).strip(" ,|-")
    return company, cleaned_role


def _parse_job_from_markdown(text: str, url: str) -> tuple[str, str, str]:
    """
    Return (company, role, description) extracted from Jina Reader markdown.

    Role   : first non-empty short line (likely the page title / h1). Tags are
             stripped first — when a fetch degrades to raw HTML instead of
             Reader markdown, the first line is markup like "<html>", and
             taking it verbatim put literal "<html>" into the role, the
             assessment prompt, and the saved filename.
    Company: heuristic scan of the first 30 lines for "at <Company>" patterns
             or a "<Company> |" / "<Company> •" separator; falls back to the
             URL-derived name.
    Description: full text, capped at 8 000 chars to stay within LLM limits.
    """
    lines = text.splitlines()

    role = ""
    for line in lines:
        stripped = _strip_html(line).lstrip("#").strip()
        if stripped and len(stripped) < 120:
            role = stripped
            break

    company = _company_from_url(url)
    for line in lines[:30]:
        # "Senior Engineer at Stripe" or "@ Stripe"
        m = re.search(r"\bat\s+([A-Z][A-Za-z0-9 &,\.]+)", line)
        if m:
            candidate = m.group(1).strip()
            if 2 < len(candidate) < 60:
                company = candidate
                break
        # "Stripe | Senior Engineer" or "Stripe • Remote"
        m = re.search(r"^([A-Z][A-Za-z0-9 &,\.]{2,40})\s*[•·|]", line.strip())
        if m:
            company = m.group(1).strip()
            break

    company, role = _normalize_title_metadata(role, company, url)

    description = text[:8000]
    return company, role, description


# A fetch that lands on an error body, a bot interstitial or a login wall still
# parses fine — it just isn't a posting. Before this guard, each one was queued
# and handed to the LLM, producing a real assessment of a job titled
# "Bad Request" or "Just a moment...". One partition held 13 such files.

# Unambiguous error/interstitial text, rejected wherever it appears in the
# title: none of these occur in a genuine job title.
_ERROR_TITLE_RE = re.compile(
    r"\b(?:"
    r"bad request|forbidden|unauthorized|access denied|access to this page"
    r"|the request could not be satisfied"
    r"|file or directory not found|page not found|page cannot be found"
    r"|just a moment|attention required|checking your browser"
    r"|are you a robot|verify you are human|security check"
    r"|example domain"
    r"|service unavailable|temporarily unavailable|too many requests"
    r"|error \d{3}|http \d{3}"
    # Jina Reader's own header fields leaking into the title.
    r"|url source:|markdown content:|published time:"
    # LinkedIn page chrome, and its search-results pages ("19 Luba jobs in
    # Netherlands") which are listings, not postings.
    r"|see who you know|jobs in\b"
    # No trailing \b on the group: several alternatives end in ':', which is
    # not a word character, so a trailing boundary could never match them.
    r")",
    re.IGNORECASE,
)  # NOSONAR — fixed alternation over trusted page text

# Residual markup in the title means extraction degraded to raw HTML. The
# tag-stripping in _parse_job_from_markdown should prevent this; belt and
# braces, because the failure is silent and expensive.
_MARKUP_TITLE_RE = re.compile(r"<\s*/?\s*[a-z!]", re.IGNORECASE)

# Page chrome meaning the extractor grabbed a login wall or a spinner rather
# than the posting. Anchored to the START of the title on purpose: a real
# posting like "Senior Engineer, Login Services" must not be rejected.
_CHROME_PREFIX_RE = re.compile(
    r"^(?:log ?in|sign ?in|email or phone|password|loading|please wait"
    r"|enable javascript|javascript is required|redirecting)\b",
    re.IGNORECASE,
)  # NOSONAR — fixed alternation over trusted page text

# A real posting runs to thousands of characters; error bodies are tiny.
_MIN_JOB_DESCRIPTION_CHARS = 300

# Matching only known error wordings catches only what we have already seen.
# qa proved the gap: r.jina.ai served a cached snapshot of example.com titled
# "Test Document" with 320 characters of body — past the length floor, and no
# error phrase to match, so it queued. The generalisable signal is the
# absence of job-posting vocabulary, not the presence of error vocabulary.
#
# Applied only to thin pages: a long page without these words is more likely
# a posting written in a way we did not anticipate than an error body, and
# rejecting it would cost more than letting it through.
_THIN_BODY_CHARS = 1500
_JOB_VOCAB_RE = re.compile(
    r"\b(?:responsibilit|qualificat|requirement|experience|skill"
    r"|you will|we are looking|who you are|what you.ll do"
    r"|apply|salary|compensation|benefit|equal opportunity"
    r"|role|position|candidate|hiring|employment|full[- ]time"
    r")",
    re.IGNORECASE,
)  # NOSONAR — fixed alternation over trusted page text


def _non_job_reason(role: str, description: str) -> str:
    """Return why this page is not a job posting, or '' if it looks like one."""
    title = role.strip()
    if _MARKUP_TITLE_RE.search(title):
        return f"the title still contains markup ({title!r})"
    if _ERROR_TITLE_RE.search(title):
        return f"the title reads as an error or interstitial page ({title!r})"
    if _CHROME_PREFIX_RE.match(title):
        return f"the title is page chrome, not a posting ({title!r})"

    body = description.strip()
    if len(body) < _MIN_JOB_DESCRIPTION_CHARS:
        return (
            f"only {len(body)} characters of content were extracted, "
            f"too little to be a job description"
        )
    if len(body) < _THIN_BODY_CHARS and not _JOB_VOCAB_RE.search(body):
        return (
            f"{len(body)} characters of content with none of the vocabulary a "
            f"job posting always carries (requirements, experience, apply, ...)"
        )
    return ""


# ── Public API ────────────────────────────────────────────────────────────────

def scrape_job_url(url: str, auto_queue: bool = True, page_text: str = "") -> str:
    """Fetch a job posting from a URL, extract the content, and optionally queue it for fitment review.

    Uses Jina Reader (r.jina.ai) to strip HTML and return clean text from any
    job board page — Greenhouse, Lever, Ashby, Workday, and company career
    pages all work well.  LinkedIn job pages are not reliably supported
    server-side; clients that can read the page themselves (the mobile app
    fetches from a residential IP where LinkedIn serves real content) pass
    the extracted content as *page_text* and no server fetch happens at all.

    Args:
        url:        Full URL to the job posting (https://...).
        auto_queue: If True (default), immediately calls queue_job so the
                    posting enters the evaluation pipeline.  If False, returns
                    the extracted content for review without queuing.
        page_text:  Optional client-supplied page content. When non-empty it
                    is trusted as the posting text and the URL is only used
                    for metadata (company-from-URL, source link).

    Pages that fetch successfully but are not postings — error bodies, bot
    interstitials, login walls — are rejected here rather than queued, so no
    LLM assessment is spent on them.
    """
    if page_text.strip():
        text = page_text
    else:
        try:
            text = _fetch_jina(url)
        except LinkedInBlockedError as exc:
            return str(exc)
        except httpx.HTTPStatusError as exc:
            return f"HTTP {exc.response.status_code} fetching {url}. The page may require login."
        except httpx.HTTPError as exc:
            return f"Failed to fetch {url}: {exc}"

    if not text.strip():
        return (
            f"No content returned from {url}. "
            "The page may require login or block automated access."
        )

    company, role, description = _parse_job_from_markdown(text, url)

    if not role:
        return (
            f"Could not extract a job title from {url}. "
            "Try queuing manually with queue_job(company, role, jd)."
        )

    non_job = _non_job_reason(role, description)
    if non_job:
        return (
            f"{url} does not look like a job posting: {non_job}. "
            "Nothing was queued and no assessment was run. "
            "If that is wrong, add it manually with queue_job(company, role, jd)."
        )

    if not auto_queue:
        preview = description[:2000]
        return (
            f"Scraped: {company} — {role}\n\n"
            f"─── EXTRACTED CONTENT (preview) ───\n"
            f"{preview}\n\n"
            f"Call scrape_job_url(url, auto_queue=True) or queue_job() to add to queue."
        )

    result = _queue_job(company=company, role=role, jd=description, source=url)
    return f"Scraped {url}\n→ {result}"


def search_jobs(  # NOSONAR
    query: str,
    location: str = "",
    num_results: int = 10,
    auto_queue: bool = False,
) -> str:
    """Search for job listings via SerpAPI Google Jobs and return matching results.

    Requires serpapi_key set in config.json.  Results can optionally be queued
    into the evaluation pipeline via auto_queue=True.

    Args:
        query:       Search query, e.g. 'Senior Software Engineer AI Python'.
        location:    Location filter, e.g. 'Seattle, WA' or 'Remote'. Optional.
        num_results: Max results to return (1-20). Default 10.
        auto_queue:  If True, queues every result immediately.  Use with care
                     for large result sets — each becomes a pending queue item.
    """
    api_key = getattr(config, "SERPAPI_KEY", "")
    if not api_key:
        return (
            "serpapi_key not set in config.json.\n"
            'Add:  "serpapi_key": "your-key"  to config.json to enable job search.\n'
            "Get a free key at https://serpapi.com"
        )

    # No "num" parameter: google_jobs doesn't support it (it belongs to the
    # google web engine) and SerpAPI rejects the whole request with HTTP 400.
    # Every search this tool made failed that way until 2026-08-30. The engine
    # returns one page (~10 results); num_results trims the display below.
    num_results = min(max(int(num_results), 1), 20)
    params: dict = {
        "engine":  "google_jobs",
        "q":       query,
        "api_key": api_key,
    }
    # SerpAPI location must be a real geographic place (e.g. "Seattle, WA").
    # "Remote" / "remote" is not a valid location — fold it into the query.
    if location:
        if location.strip().lower() == "remote":
            params["q"] = f"{query} remote"
        else:
            params["location"] = location

    try:
        response = httpx.get(_SERPAPI_BASE, params=params, timeout=_HTTP_TIMEOUT)
        response.raise_for_status()
        data = response.json()
    except httpx.HTTPStatusError as exc:
        # Surface SerpAPI's own error body — a 400 is a rejected parameter,
        # not a key problem, and "check your API key" on every status sent a
        # real outage down a key-rotation rabbit hole.
        status = exc.response.status_code
        try:
            detail = exc.response.json().get("error", "")
        except Exception:  # noqa: BLE001 — non-JSON error body
            detail = ""
        if not isinstance(detail, str):
            detail = ""
        hint = " Check your API key." if status in (401, 403) else ""
        detail_part = f": {detail}" if detail else ""
        return f"SerpAPI returned HTTP {status}{detail_part}.{hint}"
    except httpx.HTTPError as exc:
        return f"SerpAPI request failed: {exc}"

    jobs_results: list[dict] = data.get("jobs_results", [])
    if not jobs_results:
        suffix = f" in {location}" if location else ""
        return f"No results found for '{query}'{suffix}."

    header = f"═══ JOB SEARCH: {query}"
    if location:
        header += f" | {location}"
    header += " ═══"

    lines = [header, ""]
    queued_lines: list[str] = []

    for i, job in enumerate(jobs_results[:num_results], 1):
        title   = job.get("title", _UNKNOWN_ROLE)
        company = job.get("company_name", "Unknown Company")
        loc     = job.get("location", "")
        via     = job.get("via", "")
        snippet = (job.get("description") or "")[:300]

        # Prefer a direct apply link over the aggregator link
        apply_link = ""
        for opt in job.get("apply_options", []):
            if opt.get("link"):
                apply_link = opt["link"]
                break

        lines.append(f"[{i}] {company} — {title}")
        if loc:
            lines.append(f"    Location: {loc}")
        if via:
            lines.append(f"    Via:      {via}")
        if apply_link:
            lines.append(f"    Link:     {apply_link}")
        if snippet:
            lines.append(f"    Snippet:  {snippet.replace(chr(10), ' ')[:200]}...")
        lines.append("")

        if auto_queue:
            jd_text = job.get("description") or snippet
            result  = _queue_job(
                company=company,
                role=title,
                jd=jd_text,
                source=apply_link or via,
            )
            queued_lines.append(f"  {company} — {title}: {result}")

    if queued_lines:
        lines.append(_AUTO_QUEUED_HEADER)
        lines.extend(queued_lines)
    else:
        lines.append(_SCRAPE_JOB_URL_TIP)

    return "\n".join(lines)


def search_greenhouse_jobs(  # NOSONAR
    company_slug: str,
    query: str = "",
    num_results: int = 20,
    auto_queue: bool = False,
) -> str:
    """Browse open roles on a company's public Greenhouse job board. No API key required.

    Greenhouse is used by thousands of companies (Stripe, Airbnb, Dropbox, etc.).
    The company_slug is the identifier in their Greenhouse URL, e.g. for
    https://boards.greenhouse.io/stripe the slug is 'stripe'.

    Args:
        company_slug: Company identifier on Greenhouse (e.g. 'stripe', 'airbnb').
        query:        Optional keyword filter applied client-side against title
                      and description (case-insensitive).
        num_results:  Max results to display. Default 20.
        auto_queue:   If True, queues every matched result immediately.
    """
    url = f"{_GREENHOUSE_BASE}/{company_slug}/jobs?content=true"
    try:
        response = httpx.get(url, timeout=_HTTP_TIMEOUT)
        response.raise_for_status()
        data = response.json()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return (
                f"No Greenhouse board found for '{company_slug}'. "
                "Check the company slug — it appears in their Greenhouse URL: "
                "https://boards.greenhouse.io/<slug>"
            )
        return f"Greenhouse API returned HTTP {exc.response.status_code} for '{company_slug}'."
    except httpx.HTTPError as exc:
        return f"Failed to reach Greenhouse API: {exc}"

    jobs: list[dict] = data.get("jobs", [])
    if not jobs:
        return f"No open roles found on Greenhouse for '{company_slug}'."

    # Client-side filter
    if query:
        q = query.lower()
        jobs = [
            j for j in jobs
            if q in j.get("title", "").lower()
            or q in _strip_html(j.get("content", "")).lower()
        ]
        if not jobs:
            return f"No Greenhouse roles matching '{query}' at '{company_slug}'."

    company_display = company_slug.replace("-", " ").title()
    header = f"═══ GREENHOUSE: {company_display}"
    if query:
        header += f" | '{query}'"
    header += " ═══"

    lines = [header, ""]
    queued_lines: list[str] = []

    for i, job in enumerate(jobs[:num_results], 1):
        title    = job.get("title", _UNKNOWN_ROLE)
        loc_obj  = job.get("location") or {}
        loc      = loc_obj.get("name", "") if isinstance(loc_obj, dict) else str(loc_obj)
        job_url  = job.get("absolute_url", "")
        depts    = ", ".join(d["name"] for d in job.get("departments", []) if d.get("name"))
        updated  = (job.get("updated_at") or "")[:10]

        lines.append(f"[{i}] {title}")
        if loc:
            lines.append(f"    Location:   {loc}")
        if depts:
            lines.append(f"    Department: {depts}")
        if updated:
            lines.append(f"    Updated:    {updated}")
        if job_url:
            lines.append(f"    Link:       {job_url}")
        lines.append("")

        if auto_queue:
            description = _strip_html(job.get("content", ""))[:8000]
            result = _queue_job(
                company=company_display,
                role=title,
                jd=description or title,
                source=job_url,
            )
            queued_lines.append(f"  {title}: {result}")

    if queued_lines:
        lines.append(_AUTO_QUEUED_HEADER)
        lines.extend(queued_lines)
    else:
        lines.append(_SCRAPE_JOB_URL_TIP)

    return "\n".join(lines)


def search_lever_jobs(  # NOSONAR
    company_slug: str,
    query: str = "",
    num_results: int = 20,
    auto_queue: bool = False,
) -> str:
    """Browse open roles on a company's public Lever job board. No API key required.

    Lever is used by many growth-stage companies (Netflix, Reddit, Figma, etc.).
    The company_slug is the identifier in their Lever URL, e.g. for
    https://jobs.lever.co/netflix the slug is 'netflix'.

    Args:
        company_slug: Company identifier on Lever (e.g. 'netflix', 'figma').
        query:        Optional keyword filter applied client-side against title,
                      team, and description (case-insensitive).
        num_results:  Max results to display. Default 20.
        auto_queue:   If True, queues every matched result immediately.
    """
    url = f"{_LEVER_BASE}/{company_slug}?mode=json"
    try:
        response = httpx.get(url, timeout=_HTTP_TIMEOUT)
        response.raise_for_status()
        jobs: list[dict] = response.json()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return (
                f"No Lever board found for '{company_slug}'. "
                "Check the company slug — it appears in their Lever URL: "
                "https://jobs.lever.co/<slug>"
            )
        return f"Lever API returned HTTP {exc.response.status_code} for '{company_slug}'."
    except httpx.HTTPError as exc:
        return f"Failed to reach Lever API: {exc}"

    if not jobs:
        return f"No open roles found on Lever for '{company_slug}'."

    # Client-side filter
    if query:
        q = query.lower()
        jobs = [
            j for j in jobs
            if q in j.get("text", "").lower()
            or q in (j.get("categories") or {}).get("team", "").lower()
            or q in _strip_html(j.get("description", "")).lower()
            or q in _strip_html(j.get("descriptionBody", "")).lower()
        ]
        if not jobs:
            return f"No Lever roles matching '{query}' at '{company_slug}'."

    company_display = company_slug.replace("-", " ").title()
    header = f"═══ LEVER: {company_display}"
    if query:
        header += f" | '{query}'"
    header += " ═══"

    lines = [header, ""]
    queued_lines: list[str] = []

    for i, job in enumerate(jobs[:num_results], 1):
        title      = job.get("text", _UNKNOWN_ROLE)
        cats       = job.get("categories") or {}
        team       = cats.get("team", "")
        loc        = cats.get("location", "") or cats.get("allLocations", "")
        commitment = cats.get("commitment", "")  # Full-time / Part-time / Contract
        job_url    = job.get("hostedUrl", "")

        lines.append(f"[{i}] {title}")
        if team:
            lines.append(f"    Team:       {team}")
        if loc:
            lines.append(f"    Location:   {loc}")
        if commitment:
            lines.append(f"    Type:       {commitment}")
        if job_url:
            lines.append(f"    Link:       {job_url}")
        lines.append("")

        if auto_queue:
            raw_desc = job.get("description", "") + " " + job.get("descriptionBody", "")
            description = _strip_html(raw_desc)[:8000]
            result = _queue_job(
                company=company_display,
                role=title,
                jd=description or title,
                source=job_url,
            )
            queued_lines.append(f"  {title}: {result}")

    if queued_lines:
        lines.append(_AUTO_QUEUED_HEADER)
        lines.extend(queued_lines)
    else:
        lines.append(_SCRAPE_JOB_URL_TIP)

    return "\n".join(lines)


def register(mcp) -> None:
    mcp.tool()(scrape_job_url)
    mcp.tool()(search_jobs)
    mcp.tool()(search_greenhouse_jobs)
    mcp.tool()(search_lever_jobs)
