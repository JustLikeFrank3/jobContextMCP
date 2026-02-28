# [Your Name] - Job Search & Interview Prep Workspace

## ⚡ SESSION STARTUP
**Every session, before anything else:**
1. Call `get_session_context()` — loads resume, pipeline, tone profile, and personal stories in one shot.
2. If tools are unavailable or context is empty, call `check_workspace()` first.
   - If workspace is not configured, call `setup_workspace()` to create everything from scratch.
   - After setup, call `get_session_context()` to begin.

---

## WORKSPACE OVERVIEW
This workspace contains:
1. **LeetCodePractice/** - Coding interview preparation
2. **Resume [YEAR]/** - Job applications, resumes, cover letters, interview prep
3. **[SideProject]/** - Side project (optional — used for skill scanning)

## MCP SERVER
A custom MCP server lives at `/path/to/jobContextMCP/server.py`.
It is configured in `.vscode/mcp.json` and auto-connects to every session.
**Always prefer using MCP tools over re-reading files manually.**

Key tools available:
- `check_workspace()` — scan for missing config/data/folders; safe to call any time, makes no changes
- `setup_workspace(name, email, phone, linkedin, city_state, master_resume_content, ...)` — bootstrap everything from scratch; drag resume into chat and pass as master_resume_content; idempotent
- `get_job_hunt_status()` — current application pipeline
- `update_application()` — update application status/notes
- `log_application_event(company, role, event_type)` — append events to an application (phone screen, offer, note, etc.)
- `log_rejection(company, role, stage)` — log a rejection; enables pattern analysis
- `get_rejections()` — retrieve rejections with stage breakdown and bottleneck flags
- `get_daily_digest()` — morning briefing: overdue actions, stale apps, recent rejections, 3 priorities
- `weekly_summary()` — 7-day aggregate with mental health trend
- `update_compensation(company, role, base, equity_total, bonus_target_pct)` — attach comp data to an application
- `get_compensation_comparison()` — side-by-side comp table sorted by total comp
- `read_master_resume()` — full master resume with all metrics
- `assess_job_fitment(company, role, jd)` — fitment analysis context
- `generate_interview_prep_context(company, role, stage)` — structured prep context
- `get_leetcode_cheatsheet(section)` — algorithm patterns reference
- `scan_project_for_skills()` — auto-scan side project for new resume skills
- `log_mental_health_checkin(mood, energy)` — mood/energy logging
- `get_mental_health_log()` — recent check-in history
- `list_existing_materials(company)` — list resumes/cover letters
- `resume_diff(file_a, file_b)` — diff two resume versions
- `review_message(text)` — tone review: flags corporate phrases, desperation, hedging
- `get_existing_prep_file(company)` — read existing interview prep file

## BACKGROUND

- **Role/Level:** [e.g. Senior Software Engineer]
- **Location:** [City, State] — [relocation preference]
- **Core Expertise:** [Primary stack, e.g. Java/Spring Boot + Angular/TypeScript]
- **Years of Experience:** [N years at Company]
- Key achievements: [2-3 bullets with metrics]

## RECENT PROJECTS
- **[Project Name]** ([Month Year]): [Brief description + key metric]

## RESUME FOLDER

### Key Reference Files
- **`[path]/[Name] Resume - MASTER SOURCE WITH METRICS.txt`** — source of truth
- Reference materials in `06-Reference-Materials/`

### Active Interviews
⚠ For live status call `get_job_hunt_status()` via MCP.

### Resume Customization Strategy
- **Testing** → testing framework expertise, coverage %, TDD
- **Cloud** → cloud platform, IaC, migration work
- **Backend** → microservices, event-driven, SLA metrics
- **Full-Stack** → end-to-end ownership, API design
- **AI/Innovation** → AI tool adoption, measurable team impact

## INTERVIEW PREP WORKFLOW

### Coding Interviews
1. Review algorithm cheatsheet
2. Open quick reference on second monitor
3. Warm-up 1-2 problems
4. Talk through approach before coding

### Behavioral / Technical
1. Check for existing company prep file
2. Reference master resume for metrics
3. Prepare top STAR stories

## QUICK RECOVERY INSTRUCTIONS
If context is lost mid-session:
1. Call `get_session_context()` — restores everything
2. Call `get_job_hunt_status()` — live pipeline only
3. Ask: "What are we working on?" and "What's your energy like today?"
4. Call `get_mental_health_log()` if relevant

If tools are missing or workspace is broken:
1. Call `check_workspace()` — diagnoses what's missing
2. Call `setup_workspace()` — rebuilds missing files (safe to re-run, skips existing)
