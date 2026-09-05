"""Structured, tenant-scoped board discovery and expiring selectable results.

Legacy board tools retain their text/auto_queue contract. This workflow keeps
the fetched description with a stable result number; selection never scrapes
an arbitrary URL or invents a description from a title.
"""
from __future__ import annotations

import asyncio
import html
import json
import re
import time
import uuid
from contextlib import contextmanager
from typing import Literal
from urllib.parse import urlsplit

import httpx

from lib import config
from lib.db import get_connection
from lib.io import _load_json
from tools.job_queue import queue_job

Provider = Literal["greenhouse", "lever", "ashby", "recruitee"]
TTL = 3600
MAX_BOARDS = 8
ENDPOINTS = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true",
    "lever": "https://api.lever.co/v0/postings/{slug}?mode=json",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{slug}",
    "recruitee": "https://{slug}.recruitee.com/api/offers/",
}


@contextmanager
def _db():
    with get_connection() as con:
        con.execute("CREATE TABLE IF NOT EXISTS job_search_boards (provider TEXT, slug TEXT, company TEXT NOT NULL, enabled INTEGER NOT NULL, PRIMARY KEY(provider,slug))")
        con.execute("CREATE TABLE IF NOT EXISTS job_search_results (id TEXT PRIMARY KEY, expires REAL NOT NULL, results TEXT NOT NULL)")
        con.commit()
        yield con


def _validate_board(provider, slug):
    if provider not in ENDPOINTS or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9-]{0,99}", slug):
        raise ValueError("Choose greenhouse, lever, ashby, or recruitee and a board slug containing letters, numbers, or hyphens.")


def _source_board(source):
    parsed = urlsplit(str(source))
    host = parsed.hostname or ""
    providers = {"boards.greenhouse.io": "greenhouse", "job-boards.greenhouse.io": "greenhouse",
                 "jobs.lever.co": "lever", "jobs.ashbyhq.com": "ashby"}
    if host in providers:
        return providers[host], parsed.path.strip("/").split("/")[0]
    if host.endswith(".recruitee.com") and host.count(".") == 2:
        return "recruitee", host.split(".")[0]
    return None


def _boards():
    inferred = {}
    for job in _load_json(config.JOB_QUEUE_FILE, {"jobs": []}).get("jobs", []):
        try:
            key = _source_board(job.get("source", ""))
            if key:
                _validate_board(*key)
                inferred[key] = {"provider": key[0], "company_slug": key[1], "company": job.get("company") or key[1]}
        except ValueError:
            continue
    with _db() as con:
        for row in con.execute("SELECT * FROM job_search_boards"):
            key = row["provider"], row["slug"]
            if row["enabled"]:
                inferred[key] = {"provider": key[0], "company_slug": key[1], "company": row["company"]}
            else:
                inferred.pop(key, None)
    return sorted(inferred.values(), key=lambda b: (b["company"].casefold(), b["provider"]))


def list_boards() -> str:
    """List saved boards, including supported sources inferred from your queue."""
    boards = _boards()
    return "\n".join(f"{b['company']}: {b['provider']}, board slug {b['company_slug']}" for b in boards) or "No saved boards. Say save a job board to add one."


def save_board(provider: Provider, company_slug: str, company: str = "") -> str:
    """Save a public board for future searches. The slug comes from its careers URL."""
    _validate_board(provider, company_slug)
    company = company.strip() or company_slug.replace("-", " ").title()
    if len(company) > 120:
        raise ValueError("Use a company name of at most 120 characters.")
    boards = _boards()
    if len(boards) >= MAX_BOARDS and not any(b["provider"] == provider and b["company_slug"] == company_slug for b in boards):
        raise ValueError("Eight boards are already saved. Remove a board before adding another.")
    with _db() as con:
        con.execute("INSERT OR REPLACE INTO job_search_boards VALUES (?,?,?,1)", (provider, company_slug, company))
    return f"Saved {company}'s {provider} board. Say find new jobs to search your boards."


def remove_board(provider: Provider, company_slug: str) -> str:
    """Remove a board, including one automatically inferred from a queued URL."""
    _validate_board(provider, company_slug)
    with _db() as con:
        con.execute("INSERT OR REPLACE INTO job_search_boards VALUES (?,?,?,0)", (provider, company_slug, company_slug))
    return f"Removed {company_slug}'s {provider} board from future searches."


def _text(value):
    return " ".join(re.sub(r"<[^>]*>", " ", html.unescape(str(value or ""))).split())


def _normalize(board, job):
    provider = board["provider"]
    if provider == "greenhouse":
        loc = job.get("location") or {}
        role, location, source, jd = job.get("title"), loc.get("name") if isinstance(loc, dict) else loc, job.get("absolute_url"), job.get("content")
    elif provider == "lever":
        cats = job.get("categories") or {}
        sections = " ".join(str(x.get("text", "")) + " " + str(x.get("content", "")) for x in job.get("lists", []) if isinstance(x, dict))
        role, location, source = job.get("text"), cats.get("location"), job.get("hostedUrl")
        jd = " ".join(str(job.get(k) or "") for k in ("descriptionPlain", "description", "descriptionBody", "additional")) + " " + sections
        if job.get("workplaceType") == "remote":
            location = f"{location or ''} Remote"
    elif provider == "ashby":
        if job.get("isListed") is False:
            return None
        role, location, source = job.get("title"), job.get("location"), job.get("jobUrl") or job.get("applyUrl")
        jd = job.get("descriptionPlain") or job.get("descriptionHtml")
        if job.get("isRemote"):
            location = f"{location or ''} Remote"
    else:
        role, location, source = job.get("title"), job.get("location") or job.get("city"), job.get("careers_url") or job.get("careers_apply_url")
        jd = job.get("description")
    source = str(source or "")
    try:
        parsed = urlsplit(source)
        valid_url = parsed.scheme in {"https", "http"} and parsed.hostname and not parsed.username and not parsed.password
    except ValueError:
        valid_url = False
    description = _text(jd)
    if not role or not valid_url or len(description) < 80 or len(description) > 200000:
        return None
    return {"company": _text(board["company"])[:120], "role": _text(role)[:240],
            "location": _text(location)[:240], "source": source, "jd": description,
            "provider": provider}


async def _fetch(client, board):
    url = ENDPOINTS[board["provider"]].format(slug=board["company_slug"])
    try:
        async with client.stream("GET", url) as response:
            response.raise_for_status()
            chunks, size = [], 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > 8_000_000:
                    raise ValueError("Board response too large")
                chunks.append(chunk)
        data = json.loads(b"".join(chunks))
        jobs = data if isinstance(data, list) else data.get("offers" if board["provider"] == "recruitee" else "jobs", [])
        if not isinstance(jobs, list):
            raise ValueError("Invalid board response")
        return [result for job in jobs if isinstance(job, dict) and (result := _normalize(board, job))], None
    except (httpx.HTTPError, ValueError, TypeError, AttributeError):
        return [], f"{board['company']}'s {board['provider']} board could not be read. Check its slug or try again later."


async def _fetch_all(boards):
    async with httpx.AsyncClient(timeout=8, follow_redirects=False) as client:
        return await asyncio.gather(*(_bounded_fetch(client, board) for board in boards))


async def _bounded_fetch(client, board):
    try:
        return await asyncio.wait_for(_fetch(client, board), timeout=12)
    except TimeoutError:
        return [], f"{board['company']}'s board timed out. Try again later."


def discover_jobs(query: str, location: str = "", num_results: int = 5, include_known: bool = False) -> str:
    """Search up to eight saved public boards without an API key. Returns JSON with a search_id and numbered results; results expire after one hour. Use result or queue_result with that ID and number. Existing queued/tracked jobs are excluded by default."""
    words = [w for w in re.findall(r"\w+", query.casefold()) if w not in {"job", "jobs", "for"}]
    if not words or len(query) > 240 or len(location) > 120 or not 1 <= num_results <= 20:
        raise ValueError("Give a short role or keyword query and choose 1 to 20 results.")
    boards = _boards()
    if not boards:
        return json.dumps({"results": [], "message": "No saved boards. Say save a job board first, then provide the provider and company slug.", "errors": []})
    batches = asyncio.run(_fetch_all(boards[:MAX_BOARDS]))
    known = _load_json(config.JOB_QUEUE_FILE, {"jobs": []}).get("jobs", []) + _load_json(config.STATUS_FILE, {"applications": []}).get("applications", [])
    pairs = {(str(j.get("company", "")).casefold(), str(j.get("role", "")).casefold()) for j in known}
    urls = {str(j.get("source", "")).split("?")[0].rstrip("/") for j in known}
    matches, seen = [], set()
    for jobs, _ in batches:
        for job in jobs:
            key = job["source"].split("?")[0].rstrip("/")
            pair = job["company"].casefold(), job["role"].casefold()
            haystack = (job["role"] + " " + job["location"] + " " + job["jd"]).casefold()
            if key in seen or (not include_known and (pair in pairs or key in urls)):
                continue
            if not all(w in haystack for w in words) or (location and location.casefold() not in job["location"].casefold()):
                continue
            seen.add(key)
            matches.append(job)
    matches.sort(key=lambda j: (-sum(w in j["role"].casefold() for w in words), j["company"], j["role"], j["source"]))
    matches = matches[:num_results]
    search_id = uuid.uuid4().hex
    with _db() as con:
        con.execute("DELETE FROM job_search_results WHERE expires < ?", (time.time(),))
        con.execute("INSERT INTO job_search_results VALUES (?,?,?)", (search_id, time.time() + TTL, json.dumps(matches)))
    errors = [error for _, error in batches if error]
    if len(boards) > MAX_BOARDS:
        errors.append("Only the first eight saved boards were searched. Remove unwanted boards to change that set.")
    results = [{k: v for k, v in job.items() if k != "jd"} | {"number": n} for n, job in enumerate(matches, 1)]
    return json.dumps({"search_id": search_id, "results": results, "errors": errors,
                       "boards_searched": len(batches), "message": f"Found {len(results)} matching jobs from your saved boards."})


def lookup_result(search_id, result_number, connection=None):
    if connection is None:
        with _db() as con:
            return lookup_result(search_id, result_number, con)
    con = connection
    row = None
    if con.execute("SELECT 1 FROM sqlite_master WHERE name='job_search_results'").fetchone():
        row = con.execute("SELECT results FROM job_search_results WHERE id=? AND expires>=?", (search_id, time.time())).fetchone()
    if not row:
        raise ValueError("Those search results have expired or are unavailable. Search for new jobs again.")
    jobs = json.loads(row["results"])
    if isinstance(result_number, bool) or not isinstance(result_number, int) or not 1 <= result_number <= len(jobs):
        raise ValueError(f"Choose a job number from 1 to {len(jobs)}.")
    return jobs[result_number - 1]


def read_result(search_id: str, result_number: int) -> str:
    """Read the fetched job description for one result in this workspace's search."""
    return json.dumps(lookup_result(search_id, result_number))


def queue_result(search_id: str, result_number: int) -> str:
    """Add exactly one selected result, including its fetched description and source URL, to the evaluation queue. Does not apply to the employer. Repeated company/role selections return Already queued."""
    job = lookup_result(search_id, result_number)
    return queue_job(company=job["company"], role=job["role"], jd=job["jd"], source=job["source"])
