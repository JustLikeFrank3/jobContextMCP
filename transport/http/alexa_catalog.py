"""Reviewed Alexa exposure policy. New MCP actions are closed until reviewed."""
from dataclasses import dataclass
import inspect

from tools.consolidated import DOMAINS


@dataclass(frozen=True)
class Action:
    key: str
    phrase: str
    mode: str  # read, confirm, handoff
    reason: str = ""

    @property
    def intent(self):
        return "Action" + "".join(word.title() for word in self.key.replace(".", "_").split("_")) + "Intent"

    @property
    def parameters(self):
        domain, action = self.key.split(".")
        return inspect.signature(DOMAINS[domain][action][0], eval_str=True).parameters


# Explicit rows keep sensitivity/side effects independent of function naming.
_ROWS = """
applications.status|show my full application history|read
applications.update|update an application|confirm
applications.log_event|log an application event|confirm
applications.queue|queue a job description|handoff
applications.get_queue|show my job queue|read
applications.evaluate|evaluate a queued job|confirm
applications.decide|record my application decision|confirm
applications.assess|assess a saved job|read
applications.full_assessment|create a full job assessment|confirm
applications.save_assessment|save an assessment document|handoff
job_search.web|search for jobs|read
job_search.greenhouse|search a greenhouse board|read
job_search.lever|search a lever board|read
job_search.ashby|search an ashby board|read
job_search.recruitee|search a recruitee board|read
job_search.url|capture a job link|handoff
documents.generate_resume|generate a resume|confirm
documents.generate_resume_agent|generate an agentic resume|confirm
documents.generate_cover_letter|generate a cover letter|confirm
documents.submit_resume|queue resume generation|confirm
documents.submit_cover_letter|queue cover letter generation|confirm
documents.generation_status|check document generation|read
documents.export_resume_pdf|export a resume to pdf|confirm
documents.export_cover_letter_pdf|export a cover letter to pdf|confirm
documents.export_resume_latex|typeset a resume|confirm
documents.export_cover_letter_latex|typeset a cover letter|confirm
documents.save_resume|save resume text|handoff
documents.save_cover_letter|save cover letter text|handoff
documents.diff|compare two resumes|read
documents.write_latex_section|edit a latex section|handoff
documents.customization_strategy|suggest a resume strategy|read
documents.preview_story_retrieval|preview resume stories|read
documents.provenance|check document provenance|read
materials.read_master_resume|read my master resume|read
materials.update_master_resume|edit my master resume|handoff
materials.read_resume|read a saved resume|read
materials.read_reference|read reference material|read
materials.read_latex_asset|read latex source|handoff
materials.list|list my documents|read
materials.delete|delete a saved document|confirm
materials.search|search my documents|read
materials.reindex|rebuild document search|confirm
materials.reindex_stories|rebuild story search|confirm
interviews.log|log an interview debrief|confirm
interviews.list|show interview history|read
interviews.context|show a company interview process|read
interviews.upcoming|find scheduled interviews|read
interviews.prep_context|prepare for an interview|read
interviews.save_prep|save interview prep text|handoff
interviews.get_prep|read saved interview prep|read
interviews.quick_reference|show my interview quick reference|read
interviews.leetcode_cheatsheet|show coding interview patterns|read
people.log|save a contact|confirm
people.list|list my contacts|read
people.get|look up a contact|read
people.referral_chains|find referrals to a company|read
people.draft_outreach|prepare outreach drafting context|read
people.draft_reply|prepare reply drafting context|read
people.review_message|review a message|read
people.crossref_run|scan facebook contact files|handoff
people.crossref_get|show contact connections|read
people.fb_queue|show my outreach queue|read
stories.log|save a personal story|confirm
stories.update|update a story|confirm
stories.delete|delete a story|confirm
stories.ingest|capture an anecdote|confirm
stories.personal_context|find a personal story|read
stories.star_context|find an interview story|read
stories.star_all|show my star stories|read
stories.tone_log|save a writing sample|confirm
stories.tone_profile|describe my writing style|read
stories.tone_scan|learn from my writing samples|confirm
wellbeing.checkin|record a wellbeing check in|confirm
wellbeing.log|read my wellbeing history|read
wellbeing.oura_sync|sync my readiness|confirm
wellbeing.oura_log|record readiness scores|confirm
wellbeing.oura_get|read my readiness|read
wellbeing.hbdi_run|take the thinking style assessment|confirm
wellbeing.hbdi_profile|read my thinking style profile|read
brand.post_log|log a social post|confirm
brand.post_metrics|update post metrics|confirm
brand.posts|show my social posts|read
brand.github_stats|check github contributions|read
brand.portfolio|show portfolio metrics|read
brand.portfolio_refresh|refresh portfolio metrics|confirm
brand.scan_project_skills|scan local project folders|handoff
insights.daily_digest|read my daily digest|read
insights.briefing|read my voice briefing|read
insights.weekly_summary|summarize my week|read
insights.session_context|review my workspace context|read
insights.rejection_log|record a rejection|confirm
insights.rejections|review rejection patterns|read
insights.compensation_update|record compensation|confirm
insights.compensation_compare|compare compensation|read
insights.evals_results|show evaluation results|read
workspace.check|check workspace setup|read
workspace.setup|set up my workspace|handoff
certification.weekly_report|prepare a weekly certification report|confirm
certification.list_reports|list certification reports|read
certification.export|export a certification report|confirm
certification.swap_entry|replace a certification entry|confirm
certification.mark_submitted|mark a certification report submitted|confirm
certification.employer_lookup|look up an employer|confirm
certification.employer_override|edit employer directory fields|handoff
certification.state_profile|manage certification rules|confirm
"""

HANDOFF_REASONS = {
    "applications.queue": "Add the full job description through the dashboard or mobile share. Then ask me to evaluate a queued job.",
    "applications.save_assessment": "Save the complete assessment text in the dashboard. To create one from a saved job, ask me to create a full job assessment.",
    "job_search.url": "Share the job link from your phone to jobContext, or paste it in the dashboard. I can search for jobs by voice.",
    "documents.save_resume": "Save the complete resume text in the dashboard. To generate one from a saved job, ask me to generate a resume.",
    "documents.save_cover_letter": "Save the complete letter text in the dashboard. To generate one, ask me to generate a cover letter.",
    "documents.write_latex_section": "Edit LaTeX source in the desktop editor or dashboard so the exact code is preserved.",
    "materials.update_master_resume": "Edit your master resume in the dashboard or desktop editor so you can inspect the exact replacement.",
    "materials.read_latex_asset": "Open the LaTeX source in the desktop editor or dashboard. Code punctuation is not suitable for a voice reading.",
    "interviews.save_prep": "Save the full prep document in the dashboard. I can read saved interview prep or prepare interview context.",
    "people.crossref_run": "Run the contact-file scan from the desktop or dashboard with your imported files. I can read contact connections afterwards.",
    "brand.scan_project_skills": "Scan local project folders from the desktop. The cloud skill cannot access those folders. Review the results in your dashboard.",
    "workspace.setup": "Complete workspace setup in the dashboard or desktop. It needs your full resume and settings. I can check workspace setup afterwards.",
    "certification.employer_override": "Edit employer directory fields in the dashboard, where you can inspect the full address and exact field values.",
}
ACTIONS = {key: Action(key, phrase, mode, HANDOFF_REASONS.get(key, ""))
           for key, phrase, mode in (line.split("|") for line in _ROWS.strip().splitlines())}
INTENTS = {action.intent: action for action in ACTIONS.values()}

# Parameters needing exact bytes/structures are never captured as dictation.
BLOCKED_FIELDS = {"openai_api_key", "raw_json", "audience_highlights", "fields", "fb_folder",
                  "side_project_folders", "old_text", "new_text", "content", "page_text",
                  "master_resume_content", "resume_text", "body", "sent_message", "verbatim_quotes"}
# Read actions cannot acquire a write side effect through an optional slot.
FIXED = {"job_search." + action: {"auto_queue": False}
         for action in ("web", "greenhouse", "lever", "ashby", "recruitee")}


def fields(action):
    return {name: param for name, param in action.parameters.items()
            if name not in BLOCKED_FIELDS and name not in FIXED.get(action.key, {})
            and name not in {"jd", "job_description"}}


def model():
    """One reviewed action per intent; a single SearchQuery collects answers."""
    import json
    from pathlib import Path
    base = json.loads((Path(__file__).parents[2] / "packaging/alexa/en-US.json").read_text())
    lm = base["interactionModel"]["languageModel"]
    lm["intents"] = [i for i in lm["intents"] if not i["name"].startswith("Action")
                     and i["name"] not in {"AnswerIntent", "NumberAnswerIntent", "DateAnswerIntent", "ChangeFieldIntent", "RunActionIntent", "ActionStatusIntent", "MoreResultIntent", "ActionCatalogIntent", "AMAZON.YesIntent", "AMAZON.NoIntent"}]
    lm["intents"] += [{"name": a.intent, "slots": [], "samples": [a.phrase]} for a in ACTIONS.values()]
    if not any(i["name"] == "AMAZON.NavigateHomeIntent" for i in lm["intents"]):
        lm["intents"].append({"name": "AMAZON.NavigateHomeIntent", "samples": []})
    lm["intents"] += [
        {"name": "AnswerIntent", "slots": [{"name": "Answer", "type": "AMAZON.SearchQuery"}], "samples": ["my answer is {Answer}"]},
        {"name": "NumberAnswerIntent", "slots": [{"name": "Answer", "type": "AMAZON.NUMBER"}], "samples": ["the number is {Answer}"]},
        {"name": "DateAnswerIntent", "slots": [{"name": "Answer", "type": "AMAZON.DATE"}], "samples": ["the date is {Answer}"]},
        {"name": "ChangeFieldIntent", "slots": [{"name": "Field", "type": "ActionField"}], "samples": ["change {Field}", "set {Field}"]},
        {"name": "RunActionIntent", "slots": [], "samples": ["run it", "review my request"]},
        {"name": "ActionStatusIntent", "slots": [], "samples": ["check my last request", "is my request finished"]},
        {"name": "MoreResultIntent", "slots": [], "samples": ["read more", "next page"]},
        {"name": "ActionCatalogIntent", "slots": [], "samples": ["what can you do", "list available actions"]},
        {"name": "AMAZON.YesIntent", "samples": []}, {"name": "AMAZON.NoIntent", "samples": []}]
    names = sorted({name for a in ACTIONS.values() if a.mode != "handoff" for name in fields(a)})
    lm["types"] = [{"name": "ActionField", "values": [{"id": name, "name": {"value": name.replace("_", " ")}} for name in names]}]
    return base
