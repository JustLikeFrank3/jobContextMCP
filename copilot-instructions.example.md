# [Your Name] - Job Search & Interview Prep Workspace

## ⚡ SESSION STARTUP
**Every session, before anything else:**
1. Call `insights(action="session_context")` — loads resume, pipeline, tone profile, and personal stories in one shot.
2. If tools are unavailable or context is empty, call `workspace(action="check")` first.
   - If workspace is not configured, call `workspace(action="setup")` to create everything from scratch.
   - After setup, call `insights(action="session_context")` to begin.

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
- `workspace(action="check")` — scan for missing config/data/folders; safe to call any time, makes no changes
- `workspace(action="setup", name=..., email=..., phone=..., linkedin=..., city_state=..., master_resume_content=...)` — bootstrap everything from scratch; drag resume into chat and pass as master_resume_content; idempotent
- `applications(action="status")` — current application pipeline
- `applications(action="update", company=..., role=..., status=...)` — update application status/notes
- `applications(action="log_event", company=..., role=..., event_type=...)` — append events to an application (phone screen, offer, note, etc.)
- `insights(action="rejection_log", company=..., role=..., stage=...)` — log a rejection; enables pattern analysis
- `insights(action="rejections")` — retrieve rejections with stage breakdown and bottleneck flags
- `insights(action="daily_digest")` — morning briefing: overdue actions, stale apps, recent rejections, 3 priorities
- `insights(action="weekly_summary")` — 7-day aggregate with mental health trend
- `insights(action="compensation_update", company=..., role=..., base=...)` — attach comp data to an application
- `insights(action="compensation_compare")` — side-by-side comp table sorted by total comp
- `materials(action="read_master_resume")` — full master resume with all metrics
- `applications(action="assess", company=..., role=..., job_description=...)` — fitment analysis context
- `interviews(action="prep_context", company=..., role=..., stage=...)` — structured prep context
- `interviews(action="leetcode_cheatsheet")` — algorithm patterns reference
- `brand(action="scan_project_skills")` — auto-scan side project for new resume skills
- `wellbeing(action="checkin", mood=..., energy=...)` — mood/energy logging
- `wellbeing(action="log")` — recent check-in history
- `materials(action="list", company=...)` — list resumes/cover letters
- `documents(action="diff", file_a=..., file_b=...)` — diff two resume versions
- `people(action="review_message", text=...)` — tone review: flags corporate phrases, desperation, hedging
- `interviews(action="get_prep", company=...)` — read existing interview prep file

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
⚠ For live status call `applications(action="status")` via MCP.

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
1. Call `insights(action="session_context")` — restores everything
2. Call `applications(action="status")` — live pipeline only
3. Ask: "What are we working on?" and "What's your energy like today?"
4. Call `wellbeing(action="log")` if relevant

If tools are missing or workspace is broken:
1. Call `workspace(action="check")` — diagnoses what's missing
2. Call `workspace(action="setup")` — rebuilds missing files (safe to re-run, skips existing)
