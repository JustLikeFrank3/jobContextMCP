"""Shared-device summaries and explicit saved-role selection for interview prep."""
from tools.interview_prep import saved_jobs


def select_prep_job(state):
    params = state["params"]
    jobs = saved_jobs(params.get("company", ""), params.get("role", ""))
    if len(jobs) == 1:
        params.update(company=jobs[0]["company"], role=jobs[0]["role"])
        return ""
    state["phase"] = "collect"
    if not jobs:
        state["field"] = "company"
        params.pop("role", None)
        return "I couldn't match that to a saved job. Say my answer is, followed by the company name. If it is new, save the job in your workspace first."
    state["field"] = "role" if len({j['role'] for j in jobs}) > 1 else "company"
    choices = "; ".join(f"{j['role']} at {j['company']}" for j in jobs[:6])
    return f"I found {len(jobs)} saved roles. {choices}. Say my answer is, followed by the exact {state['field']}."


def prep_view(data, state, more=False):
    from transport.http.alexa_actions import plain
    title = f"Interview prep: {data['company']}"
    sections = data["sections"]
    rows = [{"primary": s["title"], "secondary": f"Practice section {i + 1}", "detail": "Full notes saved in your workspace"}
            for i, s in enumerate(sections)]
    if not more:
        state["prep_section"], state["prep_offset"] = 0, 0
        speech = f"Prep saved for {data['role']} at {data['company']}. {plain(data['summary'])} Say read more to practice the first section."
    else:
        index, offset = state.get("prep_section", 0), state.get("prep_offset", 0)
        if index >= len(sections):
            speech = "That's the end of your prep. The full document is saved in your workspace."
        else:
            section = sections[index]
            text = plain(section["body"])
            end = min(len(text), offset + 600)
            if end < len(text):
                boundary = text.rfind(" ", offset, end)
                end = boundary if boundary > offset else end
            speech = section["title"] + ". " + text[offset:end].strip() + " Say read more to continue."
            state["prep_section"] = index + 1 if end >= len(text) else index
            state["prep_offset"] = 0 if end >= len(text) else end
    return {"title": title, "summary": data["role"] + ". AI-generated practice; verify before use.",
            "speech": speech, "rows": rows, "listen": True, "footer": "Say read more to practice. Full prep is in your workspace."}
