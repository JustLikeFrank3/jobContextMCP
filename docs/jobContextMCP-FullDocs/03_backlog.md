# JobContextMCP Backlog

---

## 🐛 Open Issues

### [BUG] No CLI interface for tool invocation — forces temp script workaround
**Priority:** Medium
**Filed:** 2026-02-27

**Problem:**
MCP tools (`log_person`, `update_post_metrics`, `update_application`, etc.) are only
callable via the MCP protocol — meaning through an AI client. When tools need to be
invoked programmatically from the terminal (e.g. during development, debugging, or
agentic workflows), there is no direct call path.

The only workaround is either:
- `python3 -c "..."` — breaks on apostrophes and complex strings in zsh
- Write a temp `.py` script, run it, delete it — works but is noisy and fragile

**Proposed fix:**
Add a `cli.py` entrypoint that accepts a tool name and JSON-encoded arguments:

```bash
# Examples
.venv/bin/python3 cli.py log_person '{"name":"Hawk","relationship":"beta tester","company":"unknown","context":"..."}'
.venv/bin/python3 cli.py update_post_metrics '{"post_id":10,"impressions":163,"reactions":4}'
.venv/bin/python3 cli.py update_application '{"company":"Airbnb","role":"Software Engineer, Listings Platform","status":"phone screen complete"}'
```

Implementation sketch:
- Import all tool modules
- Build a dispatch dict: `{tool_name: fn}` from each module's public functions
- Parse `sys.argv[1]` as tool name, `sys.argv[2]` as JSON kwargs
- Call and print result

Benefits beyond the immediate fix:
- Makes tools testable/scriptable without an AI client
- Useful for CI/CD hooks, cron jobs, post-call automation scripts
- Good foundation for a future TUI or shell completion layer

**GitHub issue text (ready to file):**
> **Title:** `[BUG] No CLI interface for direct tool invocation — requires temp script workaround`
>
> Tools are only callable through the MCP protocol. Programmatic invocation from the terminal
> requires either error-prone `python3 -c` one-liners or disposable temp scripts. Propose
> adding a `cli.py` entrypoint that accepts tool name + JSON kwargs and dispatches to any
> registered tool function directly.

---

## ✅ Shipped (v0.6.0)

## Workspace Setup
- [ ] CLI interactive `setup_workspace()`
- [ ] Copilot chat wrapper `setup_workspace_conversational()`
- [ ] Config.json generation
- [ ] Multi-language prep folder support (Java, Python, C++, etc.)
- [ ] Starter template files for each language

## Branding
- [ ] Primary logo: brain in magnifying glass (SVG + PNG)
- [ ] Horizontal banner for README (SVG + PNG)
- [ ] Favicons: 32x32, 16x16
- [ ] Branding guide (colors, fonts, usage instructions)

## Templates / Starter Data
- [ ] Resume placeholders
- [ ] Pipeline JSON example
- [ ] Materials/interview questions

## Integration
- [ ] MCP client compatibility
- [ ] VS Code Copilot testing
- [ ] README + markdown badges

## Monetization Prep
- [ ] Packaged zip for self-hosted product
- [ ] Hosted MCP workspace prototype
- [ ] Optional subscription/update system

## Marketing
- [ ] Demo video/GIF of CLI + Copilot setup
- [ ] Social media / dev community posts
- [ ] Landing page or GitHub project page for premium packages
