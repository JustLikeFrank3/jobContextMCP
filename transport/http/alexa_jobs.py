"""Compact search views. Selection is resolved from tenant storage, not slots."""
from tools.job_discovery import lookup_result


def search_view(data, state, more=False):
    state["search_id"] = data.get("search_id")
    jobs = data.get("results", [])
    offset = state.get("job_offset", 0) + 3 if more else 0
    if offset >= len(jobs):
        offset = 0
    state["job_offset"] = offset
    summary = data.get("message", "No matching jobs found.")
    if data.get("errors"):
        summary += " " + " ".join(data["errors"])
    rows = [{"primary": f"{j['number']}. {j['company']}", "secondary": j["role"],
             "detail": j["location"], "number": str(j["number"])} for j in jobs]
    speech = summary + " " + " ".join(f"Job {j['number']}: {j['role']} at {j['company']}, {j['location'] or 'location not listed'}." for j in jobs[offset:offset + 3])
    footer = "Say tell me about job two, or queue job two."
    if jobs:
        speech += " " + footer
        if len(jobs) > 3:
            speech += " Say read more for the next three."
    return {"title": "New job matches", "summary": summary, "speech": speech,
            "rows": rows, "listen": True, "footer": footer if jobs else "Try a broader query or save another board.",
            "search_id": data.get("search_id") if jobs else None}


def selected_job(con, state):
    return lookup_result(state.get("search_id"), state["params"]["result_number"], con)


def detail_view(job, number):
    excerpt = job["jd"][:600]
    if len(job["jd"]) > 600:
        excerpt = excerpt.rsplit(" ", 1)[0] + ". The full description will be saved when you queue it."
    title = f"Job {number}: {job['company']}"
    summary = f"{job['role']}. {job['location'] or 'Location not listed'}. {excerpt}"
    footer = f"Say queue job {number} to review adding this job, or tell me about another job number."
    return {"title": title, "summary": summary, "speech": title + ". " + summary + " " + footer,
            "rows": [], "listen": True, "footer": footer}
