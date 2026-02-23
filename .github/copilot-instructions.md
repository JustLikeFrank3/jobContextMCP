# [Your Name] — Job Search & Interview Prep Workspace

## ⚡ MANDATORY SESSION STARTUP
**Call `get_session_context()` as your FIRST action in EVERY session. No exceptions.**
This single call loads your master resume, tone profile, personal context, and live job pipeline.
If you skip this, you are flying blind. Honor the system.

> **Note for users:** Copy this file to your Resume folder's `.github/copilot-instructions.md`
> and fill in your personal details there. That folder should not be a git repo — keep your
> private information out of this one.

---

## MCP SERVER
Server lives at the path configured in `.vscode/mcp.json`.
Always prefer MCP tools over reading files manually.

### Complete Tool Reference

**Session & Context**
- `get_session_context()` — full context in one shot (call this first)
- `read_master_resume()` — master resume only
- `get_personal_context(tag, person)` — personal stories and STAR narratives
- `get_star_story_context(company, role, tags)` — tagged STAR stories with metric bullets

**Job Hunt**
- `get_job_hunt_status()` — live application pipeline
- `update_application(company, role, status, notes, next_steps, contact)` — update pipeline

**Resume & Cover Letter**
- `list_existing_materials(company)` — list saved resumes and cover letters
- `read_existing_resume(filename)` — read a specific resume file
- `read_reference_file(filename)` — read from reference materials folder
- `save_resume_txt(filename, content)` — save resume draft to disk
- `save_cover_letter_txt(filename, content)` — save cover letter draft to disk
- `export_resume_pdf(filename)` — export resume .txt to formatted PDF
- `export_cover_letter_pdf(filename)` — export cover letter .txt to formatted PDF

**Fitment & Interview**
- `assess_job_fitment(company, role, job_description)` — fitment analysis against master resume
- `get_customization_strategy(role_type)` — which skills/stories to lead with (testing, cloud, backend, fullstack, ai_innovation, data_engineering, iot)
- `generate_interview_prep_context(company, role, stage, job_description)` — structured prep context
- `get_existing_prep_file(company)` — find existing interview prep files
- `get_interview_quick_reference()` — algorithm cheatsheet, system design framework, pre-interview checklist
- `get_leetcode_cheatsheet(section)` — algorithm pattern reference

**Outreach & People**
- `draft_outreach_message(contact, company, context, message_type)` — outreach in your voice
- `log_person(name, relationship, company, context, tags, contact_info, outreach_status, notes, sent_message)` — save/update a contact
- `get_people(name, company, tag, outreach_status)` — query contacts

**Tone & Voice**
- `get_tone_profile()` — your writing voice samples
- `log_tone_sample(text, source, context)` — ingest a new writing sample
- `scan_materials_for_tone(category, company, limit, force)` — bulk ingest from resume folder

**RAG / Search**
- `search_materials(query, category)` — semantic search across all materials
- `reindex_materials()` — rebuild RAG index after adding new files

**Health**
- `log_mental_health_checkin(mood, energy, notes, productive)` — daily check-in
- `get_mental_health_log(days)` — recent check-in history

**Side Project**
- `scan_spicam_for_skills()` — scan side project for new resume-worthy skills

---

## QUICK RECOVERY (if context is ever lost mid-session)
1. `get_session_context()` — restores everything
2. `get_job_hunt_status()` — live pipeline only
3. `get_tone_profile()` — voice only
4. Ask: "What are we working on?" and "What's your energy like today?"
5. `get_mental_health_log()` if relevant

---

## BEHAVIORAL RULES
- Never draft a cover letter, outreach message, or resume bullet without first loading the tone profile
- Always be honest about job fitment — do not inflate scores to be encouraging
- Proactively update `update_application()` whenever pipeline status changes in conversation
- Proactively log new contacts with `log_person()` when someone new is mentioned
