# [Your Name] - Job Search & Interview Prep Workspace

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
- `get_job_hunt_status()` — current application pipeline
- `update_application()` — update application status/notes
- `read_master_resume()` — full master resume with all metrics
- `assess_job_fitment(company, role, jd)` — fitment analysis context
- `generate_interview_prep_context(company, role, stage)` — structured prep context
- `get_leetcode_cheatsheet(section)` — algorithm patterns reference
- `scan_project_for_skills()` — auto-scan side project for new resume skills
- `log_mental_health_checkin(mood, energy)` — mood/energy logging
- `get_mental_health_log()` — recent check-in history
- `list_existing_materials(company)` — list resumes/cover letters
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
If context is lost:
1. Call `get_job_hunt_status()` — live pipeline
2. Call `read_master_resume()` — full background
3. Check most recent files in resume folder
4. Ask: "What are we working on?" and "What's your energy like today?"
5. Call `get_mental_health_log()` if needed
