"""Public Remote + Mobile Architecture doc page (served at /architecture).
Self-contained — design tokens + Google Fonts inlined, mirrors landing.py style.
"""
from __future__ import annotations

ARCHITECTURE_HTML: str = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Remote &amp; Mobile Architecture &mdash; jobContext</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500;600;700&display=swap');
:root {
  --ink-950: #070B14; --ink-900: #0A0F1C; --ink-850: #0B1220;
  --ink-800: #0F172A; --ink-700: #111A2B; --ink-600: #16213A;
  --ink-500: #1B2A44; --ink-450: #22324E;
  --line: #23324D; --line-soft: #1A2740; --line-strong: #2E4366;
  --cyan-500: #06B6D4; --cyan-400: #22C7E0; --cyan-300: #6FE0EE;
  --green-500: #22C55E;
  --text: #F2F6FC; --text-strong: #FFFFFF; --text-soft: #D7E3F8;
  --muted: #9AA8BF; --faint: #6B7A93;
  --font-body: 'Space Grotesk', system-ui, sans-serif;
  --font-mono: 'JetBrains Mono', monospace;
}
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
html { font-size: 16px; scroll-behavior: smooth; }
body {
  background: linear-gradient(160deg, var(--ink-900) 0%, var(--ink-850) 100%);
  color: var(--text); font-family: var(--font-body);
  min-height: 100vh; line-height: 1.6;
}
a { color: var(--cyan-500); text-decoration: none; }
a:hover { color: var(--cyan-400); text-decoration: underline; }

/* ---- Nav ---- */
nav {
  position: sticky; top: 0; z-index: 100;
  background: rgba(10,15,28,.92); backdrop-filter: blur(12px);
  border-bottom: 1px solid var(--line); padding: 0 1.5rem;
}
.nav-inner {
  max-width: 900px; margin: 0 auto;
  display: flex; align-items: center; justify-content: space-between; height: 54px;
}
.brand { display: flex; align-items: center; gap: .5rem; font-weight: 600; color: var(--text-strong); }
.brand .c { color: var(--cyan-500); }
.nav-links { display: flex; gap: 1.5rem; font-size: .875rem; }
.nav-links a { color: var(--muted); }
.nav-links a:hover { color: var(--text); text-decoration: none; }

/* ---- Layout ---- */
.wrap { max-width: 900px; margin: 0 auto; padding: 3rem 1.5rem 5rem; }
.page-eyebrow {
  font-size: .75rem; font-weight: 600; letter-spacing: .12em;
  text-transform: uppercase; color: var(--cyan-500); margin-bottom: .75rem;
}
h1 { font-size: 2.2rem; font-weight: 700; color: var(--text-strong); line-height: 1.15; margin-bottom: 1rem; }
.subtitle { font-size: 1.1rem; color: var(--muted); margin-bottom: 3rem; max-width: 640px; }

/* ---- Section headings ---- */
.doc-section { margin-bottom: 3rem; }
.doc-section h2 {
  font-size: 1.3rem; font-weight: 700; color: var(--text-strong);
  margin-bottom: 1rem; padding-bottom: .5rem;
  border-bottom: 1px solid var(--line);
}
.doc-section h3 {
  font-size: 1rem; font-weight: 600; color: var(--cyan-300);
  margin: 1.5rem 0 .5rem;
}
.doc-section p { color: var(--muted); font-size: .95rem; margin-bottom: .75rem; }
.doc-section ul { padding-left: 1.5rem; color: var(--muted); font-size: .95rem; }
.doc-section ul li { margin-bottom: .35rem; }

/* ---- Diagram ---- */
.diagram-wrap {
  background: var(--ink-800); border: 1px solid var(--line);
  border-radius: 8px; padding: 1.25rem 1.5rem; margin: 1rem 0;
  overflow-x: auto;
}
pre {
  font-family: var(--font-mono); font-size: .82rem;
  color: var(--text-soft); line-height: 1.55; white-space: pre;
}
code {
  font-family: var(--font-mono); font-size: .875rem;
  background: var(--ink-500); border: 1px solid var(--line);
  padding: .15em .4em; border-radius: 4px; color: var(--cyan-300);
}

/* ---- Transport cards ---- */
.transport-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 1rem; margin: 1rem 0;
}
.transport-card {
  background: var(--ink-700); border: 1px solid var(--line);
  border-radius: 10px; padding: 1.25rem;
}
.transport-card h4 {
  font-size: .95rem; font-weight: 600; color: var(--text-strong); margin-bottom: .4rem;
}
.transport-card p { font-size: .875rem; color: var(--muted); }
.tag {
  display: inline-block; padding: .15em .6em; border-radius: 4px;
  font-size: .75rem; font-weight: 600; margin-bottom: .6rem;
  background: var(--ink-500); color: var(--cyan-300); border: 1px solid var(--line);
}

/* ---- Non-goals ---- */
.nongoals {
  display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; margin-top: 1rem;
}
.ng-box {
  background: var(--ink-700); border: 1px solid var(--line); border-radius: 8px; padding: 1rem 1.25rem;
}
.ng-box h4 { font-size: .85rem; font-weight: 700; margin-bottom: .5rem; }
.ng-box.do-not h4 { color: #F87171; }
.ng-box.do h4 { color: var(--green-500); }
.ng-box ul { padding-left: 1.2rem; color: var(--muted); font-size: .875rem; }
.ng-box ul li { margin-bottom: .3rem; }

/* ---- See also ---- */
.see-also {
  margin-top: 3.5rem; padding: 1.5rem;
  background: var(--ink-700); border: 1px solid var(--line); border-radius: 10px;
}
.see-also h4 {
  font-size: .75rem; font-weight: 600; letter-spacing: .1em;
  text-transform: uppercase; color: var(--muted); margin-bottom: 1rem;
}
.doc-links { display: flex; flex-wrap: wrap; gap: .75rem; }
.doc-link {
  display: flex; align-items: flex-start; gap: .75rem; padding: 1rem 1.25rem;
  background: var(--ink-600); border: 1px solid var(--line);
  border-radius: 8px; text-decoration: none; flex: 1; min-width: 220px;
  transition: border-color .15s;
}
.doc-link:hover { border-color: var(--cyan-500); text-decoration: none; }
.doc-link-icon { color: var(--cyan-500); margin-top: .1rem; flex-shrink: 0; }
.doc-link-text strong { display: block; color: var(--text-strong); font-size: .95rem; margin-bottom: .2rem; }
.doc-link-text span { color: var(--muted); font-size: .825rem; }

/* ---- Footer ---- */
footer { border-top: 1px solid var(--line); padding: 1.5rem; }
.foot-inner {
  max-width: 900px; margin: 0 auto;
  display: flex; align-items: center; justify-content: space-between;
  flex-wrap: wrap; gap: .75rem;
}
.foot-links { display: flex; gap: 1.25rem; flex-wrap: wrap; }
.foot-links a { color: var(--muted); font-size: .875rem; }
.foot-links a:hover { color: var(--text); text-decoration: none; }
.muted { color: var(--muted); font-size: .875rem; }

@media (max-width: 600px) {
  .nongoals { grid-template-columns: 1fr; }
}
</style>
</head>
<body>

<nav>
  <div class="nav-inner">
    <a class="brand" href="/">
      <svg viewBox="0 0 320 290" width="22" height="20" aria-label="jobContext">
        <path d="M268.2 124.5 A80 80 0 1 0 268.2 175.5" fill="none" stroke="var(--cyan-500)" stroke-width="46" stroke-linecap="round"/>
        <circle cx="84" cy="54" r="27" fill="#fff"/>
        <path d="M84 98 L84 207 Q84 250 41 250" fill="none" stroke="#fff" stroke-width="40" stroke-linecap="round"/>
      </svg>
      <span>job<span class="c">Context</span></span>
    </a>
    <div class="nav-links">
      <a href="/">Home</a>
      <a href="/why">Why</a>
      <a href="/setup">Get started</a>
      <a href="/login">Sign in</a>
    </div>
  </div>
</nav>

<div class="wrap">
  <div class="page-eyebrow">Architecture</div>
  <h1>Remote &amp; Mobile Architecture</h1>
  <p class="subtitle">How jobContext exposes its tools over HTTP, SSE, and WebSocket for iPad, browser, and Open WebUI clients without breaking existing local stdio MCP support.</p>

  <!-- Current vs Target -->
  <div class="doc-section">
    <h2>Goal</h2>
    <p>Add remote and mobile access so jobContext can be used from iPad, browser clients, Open WebUI, VS Code tunnels, and future web UIs without touching the existing Claude Desktop stdio path.</p>
    <h3>Current</h3>
    <div class="diagram-wrap"><pre>Claude Desktop
    ↓ stdio
jobContextMCP</pre></div>
    <h3>Target</h3>
    <div class="diagram-wrap"><pre>                ┌─────────────────────┐
                │ Claude Desktop      │
                │ (existing stdio)    │
                └──────────┬──────────┘
                           │ stdio
                ┌──────────▼──────────┐
                │   jobContextMCP     │
                │ core tools/services │
                └──────────┬──────────┘
                           │
         ┌─────────────────┼─────────────────┐
         │                 │                 │
       REST              SSE             WebSocket
         │                 │                 │
         ▼                 ▼                 ▼
   Open WebUI         Browser UI        iPad clients
   Custom app         Streaming         Remote agents</pre></div>
  </div>

  <!-- Design principle -->
  <div class="doc-section">
    <h2>Critical design requirement</h2>
    <p>Business logic must not be tightly coupled to any transport layer. The layered architecture:</p>
    <div class="diagram-wrap"><pre>transport/
    mcp_stdio/    ← existing Claude Desktop path (untouched)
    http/         ← FastAPI REST + SSE
    websocket/    ← future iPad/agent clients

services/
    resume_service.py
    job_analysis_service.py
    retrieval_service.py
    tone_service.py
    langgraph_service.py

repositories/
    vector_store/
    documents/
    embeddings/

workflows/
    langgraph/</pre></div>
    <p>MCP tools become thin wrappers around the shared service layer. No duplicated logic between HTTP and MCP.</p>
  </div>

  <!-- Transports -->
  <div class="doc-section">
    <h2>Transport layers</h2>
    <div class="transport-grid">
      <div class="transport-card">
        <div class="tag">REST</div>
        <h4>HTTP API</h4>
        <p>FastAPI endpoints for job analysis, resume generation, story retrieval, and tone search. JSON in, structured data out.</p>
      </div>
      <div class="transport-card">
        <div class="tag">SSE</div>
        <h4>Server-Sent Events</h4>
        <p>Streaming progress for resume generation, live job analysis, and multi-step LangGraph workflows. Essential for browser and iPad UX.</p>
      </div>
      <div class="transport-card">
        <div class="tag">WebSocket</div>
        <h4>WebSocket</h4>
        <p>Bidirectional channel for iPad clients and remote agent sessions requiring low-latency two-way communication.</p>
      </div>
      <div class="transport-card">
        <div class="tag">stdio</div>
        <h4>MCP stdio</h4>
        <p>Existing Claude Desktop transport. Preserved exactly as-is. MCP tools delegate to services rather than owning logic.</p>
      </div>
    </div>
  </div>

  <!-- Key endpoints -->
  <div class="doc-section">
    <h2>Key REST endpoints</h2>
    <h3>Job analysis</h3>
    <div class="diagram-wrap"><pre>POST /api/jobs/analyze
{
  "job_description": "...",
  "target_role": "...",
  "resume_id": "default"
}</pre></div>
    <p>Returns keyword extraction, match score, missing skills, recommended STAR stories, and suggested resume edits.</p>

    <h3>Resume generation</h3>
    <div class="diagram-wrap"><pre>POST /api/resumes/generate</pre></div>
    <p>Returns a tailored resume in markdown and ATS-optimized form. PDF export available via the LaTeX pipeline.</p>

    <h3>Streaming workflow</h3>
    <div class="diagram-wrap"><pre>GET /api/workflows/stream/{session_id}</pre></div>
    <p>SSE stream of multi-step LangGraph workflow progress. Resumable sessions planned.</p>

    <h3>Story &amp; tone search</h3>
    <div class="diagram-wrap"><pre>POST /api/stories/search
POST /api/tone/search</pre></div>
    <p>Semantic search over STAR stories and tone samples with relevance scores.</p>
  </div>

  <!-- Auth -->
  <div class="doc-section">
    <h2>Authentication</h2>
    <p>API keys initially, JWT when needed.</p>
    <div class="diagram-wrap"><pre>Authorization: Bearer &lt;token&gt;</pre></div>
    <p>Token stored in <code>.env</code>. Microsoft Entra ID (MSAL) integration for the hosted dashboard.</p>
  </div>

  <!-- Remote access -->
  <div class="doc-section">
    <h2>Remote access</h2>
    <p>Tailscale-compatible, LAN-safe by default, configurable host binding. Not exposed publicly without explicit opt-in.</p>
    <div class="diagram-wrap"><pre>HOST=127.0.0.1
PORT=8000
ENABLE_REMOTE=false</pre></div>
  </div>

  <!-- Non-goals -->
  <div class="doc-section">
    <h2>Non-goals &amp; priorities</h2>
    <div class="nongoals">
      <div class="ng-box do-not">
        <h4>Do NOT</h4>
        <ul>
          <li>Rewrite the MCP server</li>
          <li>Remove stdio support</li>
          <li>Tightly bind UI to backend</li>
          <li>Make LangGraph the only orchestration path</li>
          <li>Over-engineer auth initially</li>
        </ul>
      </div>
      <div class="ng-box do">
        <h4>Prioritize</h4>
        <ul>
          <li>Modularity</li>
          <li>Transport independence</li>
          <li>Mobile and browser usability</li>
          <li>Clean service abstraction</li>
        </ul>
      </div>
    </div>
  </div>

  <!-- See also -->
  <div class="see-also">
    <h4>See also</h4>
    <div class="doc-links">
      <a class="doc-link" href="/setup">
        <svg class="doc-link-icon" viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.8">
          <circle cx="12" cy="12" r="10"/>
          <path d="M12 8v4l3 3"/>
        </svg>
        <div class="doc-link-text">
          <strong>Getting started</strong>
          <span>Set up jobContext with Claude Desktop in five minutes.</span>
        </div>
      </a>
      <a class="doc-link" href="https://github.com/JustLikeFrank3/jobContextMCP" target="_blank">
        <svg class="doc-link-icon" viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.8">
          <path d="M9 19c-4 1.3-4-2.2-6-2.7M15 21v-3.4a3 3 0 0 0-.8-2.3c2.8-.3 5.6-1.4 5.6-6a4.6 4.6 0 0 0-1.3-3.2 4.3 4.3 0 0 0-.1-3.2s-1-.3-3.4 1.3a11.6 11.6 0 0 0-6 0C6.6 1.6 5.6 1.9 5.6 1.9a4.3 4.3 0 0 0-.1 3.2A4.6 4.6 0 0 0 4.2 8.3c0 4.6 2.8 5.7 5.6 6a3 3 0 0 0-.8 2.3V21"/>
        </svg>
        <div class="doc-link-text">
          <strong>GitHub Repository</strong>
          <span>Full source code, issues, and contribution guides.</span>
        </div>
      </a>
    </div>
  </div>
</div>

<footer>
  <div class="foot-inner">
    <span class="muted">&copy; 2026 jobContext &mdash; The memory layer for your career.</span>
    <div class="foot-links">
      <a href="/">Home</a>
      <a href="/why">Why jobContext</a>
      <a href="/setup">Getting started</a>
      <a href="/architecture">Architecture</a>
      <a href="https://github.com/JustLikeFrank3/jobContextMCP">GitHub</a>
      <a href="/login">Sign in</a>
    </div>
  </div>
</footer>

</body>
</html>
'''


def architecture_html() -> str:
    return ARCHITECTURE_HTML
