"""Public architecture doc page (served at /architecture).
Self-contained — design tokens + Google Fonts inlined, mirrors landing.py style.
Describes the shipped system: one capability layer behind MCP, WebMCP, HTTP,
desktop, and mobile; multi-tenant cloud; sync; truth gate + evals.
"""
from __future__ import annotations

ARCHITECTURE_HTML: str = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Architecture &mdash; jobContext</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500;600;700&display=swap');
:root {
  --ink-950: #070B14; --ink-900: #0A0F1C; --ink-850: #0B1220;
  --ink-800: #0F172A; --ink-700: #111A2B; --ink-600: #16213A;
  --ink-500: #1B2A44; --ink-450: #22324E;
  --line: #23324D; --line-soft: #1A2740; --line-strong: #2E4366;
  --cyan-500: #00B5C8; --cyan-400: #22C7E0; --cyan-300: #6FE0EE;
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
.subtitle { font-size: 1.1rem; color: var(--muted); margin-bottom: 3rem; max-width: 680px; }

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
.doc-section b { color: var(--text-soft); font-weight: 600; }

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
/* Mermaid: before render the source shows as a plain code block (graceful
   fallback if the CDN script is blocked); once processed, center the SVG. */
pre.mermaid[data-processed="true"] { display: flex; justify-content: center; }
pre.mermaid svg { max-width: 100%; height: auto; }
code {
  font-family: var(--font-mono); font-size: .875rem;
  background: var(--ink-500); border: 1px solid var(--line);
  padding: .15em .4em; border-radius: 4px; color: var(--cyan-300);
}

/* ---- Transport / surface cards ---- */
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
</style>
</head>
<body>

<nav>
  <div class="nav-inner">
    <a class="brand" href="/">
      <svg viewBox="0 0 320 320" width="24" height="24" aria-label="jobContext">
        <circle cx="160" cy="160" r="153" fill="#0A0F1C"/>
        <circle cx="160" cy="160" r="153" fill="none" stroke="var(--cyan-500)" stroke-width="10"/>
        <g transform="translate(-12 0)">
          <path d="M234 118 A56 56 0 1 0 234 202" fill="none" stroke="var(--cyan-500)" stroke-width="32" stroke-linecap="round"/>
          <circle cx="100" cy="112" r="19" fill="#fff"/>
          <path d="M100 142 L100 205 Q100 230 74 230" fill="none" stroke="#fff" stroke-width="30" stroke-linecap="round"/>
        </g>
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
  <h1>One capability layer, every surface</h1>
  <p class="subtitle">jobContext is a single Python capability layer &mdash; 12 consolidated domain tools over a shared service layer and SQLite &mdash; shipped three ways: a native desktop app, a multi-tenant cloud, and a mobile companion. AI assistants, in-browser agents, the dashboard, the CLI, and automation all call the same tools.</p>

  <!-- Big picture -->
  <div class="doc-section">
    <h2>The big picture</h2>
    <div class="diagram-wrap"><pre class="mermaid">
flowchart TB
  subgraph AGENTS["AI agents"]
    direction LR
    MCPC["Claude · Copilot · Cursor · Windsurf<br/><i>MCP — stdio / Streamable HTTP</i>"]
    WEBA["ChatGPT desktop · Chrome OT · Edge<br/><i>WebMCP — document.modelContext</i>"]
  end
  subgraph HUMANS["Human &amp; automation surfaces"]
    direction LR
    DASH["React dashboard<br/><i>web + desktop</i>"]
    CLI["CLI · REST API<br/><i>automation, CI</i>"]
    MOB["Mobile app<br/><i>share-sheet capture</i>"]
  end
  subgraph CORE["jobContext capability layer"]
    FAC["<b>12 consolidated domain tools · 104 actions</b><br/>applications · job_search · documents · materials · people · interviews<br/>stories · brand · insights · wellbeing · certification · workspace"]
    SVC["shared service layer — one implementation of every capability,<br/>no logic duplicated per transport"]
    DB[("SQLite + JSON audit trail<br/>per-tenant partitions · files")]
    FAC --> SVC
    SVC --> DB
  end
  MCPC --> FAC
  WEBA --> FAC
  DASH --> FAC
  CLI --> FAC
  MOB --> FAC
  classDef hl stroke:#00B5C8,stroke-width:1.5px;
  class FAC hl
    </pre></div>
    <p>Each tool takes an <code>action</code> parameter; a coverage test guarantees every capability of the historical 88-function surface stays reachable through the facades, so no client &mdash; AI or human &mdash; ever sees a stale subset. The agent is optional: the same tools serve the CLI, cron jobs, the dashboard, and the mobile app.</p>
  </div>

  <!-- Three deployments -->
  <div class="doc-section">
    <h2>Three deployments, one codebase</h2>
    <div class="transport-grid">
      <div class="transport-card">
        <div class="tag">Desktop</div>
        <h4>Tauri 2 + sidecar</h4>
        <p>A native shell embedding the full Python server as a signed sidecar. Local SQLite, loopback-only, embedded AI chat (BYOK or local Ollama), one-click MCP connect, automatic updates.</p>
      </div>
      <div class="transport-card">
        <div class="tag">Cloud</div>
        <h4>Multi-tenant on AKS</h4>
        <p>The same server behind Microsoft Entra ID at jobcontext.ai. Every tenant gets an isolated data partition; per-request context routing keeps them apart. CI-driven deploys with an eval smoke gate.</p>
      </div>
      <div class="transport-card">
        <div class="tag">Mobile</div>
        <h4>Expo companion (iOS)</h4>
        <p>Share-sheet capture with on-device page extraction &mdash; the phone reads postings that block datacenter IPs. Talks to the cloud with a keychain-stored API key.</p>
      </div>
    </div>
    <p><i style="color:var(--faint)">Desktop creates knowledge, mobile captures reality, cloud synchronizes.</i></p>
  </div>

  <!-- Transports -->
  <div class="doc-section">
    <h2>Client transports</h2>
    <div class="transport-grid">
      <div class="transport-card">
        <div class="tag">MCP · stdio</div>
        <h4>Local AI clients</h4>
        <p>Claude Desktop, VS Code + Copilot, Cursor, and Windsurf spawn the server directly. The original transport, still first-class.</p>
      </div>
      <div class="transport-card">
        <div class="tag">MCP · Streamable HTTP</div>
        <h4>Remote AI clients</h4>
        <p>Claude.ai, Cursor, and VS Code connect to <code>/mcp</code> over OAuth (dynamic client registration + PKCE proxied to Entra). Runs stateless &mdash; every call is self-contained, so deploys never strand a connector session.</p>
      </div>
      <div class="transport-card">
        <div class="tag">WebMCP</div>
        <h4>In-browser agents</h4>
        <p>The cloud dashboard republishes the server's tool list in-page via <code>document.modelContext</code>. ChatGPT desktop's browser, Chrome's origin trial, and Edge preview drive the workspace with no connector setup.</p>
      </div>
      <div class="transport-card">
        <div class="tag">REST</div>
        <h4>Dashboard, CLI, mobile</h4>
        <p>FastAPI serves the React dashboard, the HTTP API the mobile app and automation scripts use, and Prometheus metrics.</p>
      </div>
    </div>
  </div>

  <!-- WebMCP -->
  <div class="doc-section">
    <h2>The WebMCP bridge</h2>
    <p>The dashboard is itself an agent surface. On sign-in, the bridge fetches <code>tools/list</code> from <code>/mcp</code> and registers each tool <b>verbatim</b> &mdash; names, descriptions, and schemas &mdash; as in-page WebMCP tools. There is no second tool surface to maintain, so what a browser agent sees can never drift from what an MCP client sees.</p>
    <div class="diagram-wrap"><pre class="mermaid">
sequenceDiagram
  participant A as In-browser agent
  participant B as WebMCP bridge (in-page)
  participant M as /mcp (stateless Streamable HTTP)
  Note over B: on sign-in: fetch tools/list,<br/>register every tool verbatim
  A->>B: document.modelContext tool call
  B->>M: same-origin POST (session cookie)
  Note over M: CSRF guard — the cookie is<br/>ignored on cross-site requests
  M-->>B: JSON-RPC result from the same 12 facades<br/>every MCP client gets
  B-->>A: tool result
    </pre></div>
    <p><b>Security:</b> an in-page agent acts as the signed-in user, inside their session &mdash; the same trust boundary as the user clicking the dashboard by hand. Because the session cookie is ambient, the middleware ignores it on cross-site <code>/mcp</code> requests (<code>Sec-Fetch-Site</code>, with an <code>Origin</code>/<code>Host</code> fallback), so a hostile page can't ride your login. Bearer auth is untouched.</p>
  </div>

  <!-- Cloud internals -->
  <div class="doc-section">
    <h2>Inside the cloud</h2>
    <h3>Tenant isolation</h3>
    <p>Every tenant's data lives under its own partition; per-request context routing pins each request &mdash; and each background job &mdash; to exactly one partition. Background work goes through a <b>control plane</b>: durable work-item rows plus an in-process dispatcher, so long tasks (URL capture, document generation, eval runs, weekly certification) survive restarts and carry their partition with them.</p>
    <h3>Auth that fails honestly</h3>
    <p>Entra ID for browsers, OAuth for connectors, personal access tokens for mobile and automation. Token verification distinguishes "invalid" from "can't verify right now": a key-fetch failure returns 503 with <code>Retry-After</code>, never a false 401 &mdash; so a transient outage never logs anyone out or breaks a connector.</p>
    <h3>Observability</h3>
    <p>A zero-dependency metrics library exports Prometheus metrics; in-cluster Prometheus + Grafana dashboards are checked in as code. Incident history lives in PR post-mortems, not tribal memory.</p>
  </div>

  <!-- Sync -->
  <div class="doc-section">
    <h2>Desktop &#8646; cloud sync</h2>
    <p>Journal-based and bidirectional: database triggers append every row change to a sync journal; peers exchange journals and resolve upserts last-writer-wins by timestamp. Files sync by SHA-256 manifest, and deletions propagate as tombstones that out-date stale copies instead of resurrecting them. Capture on your phone, assess on your desktop, connect from the cloud &mdash; same data everywhere.</p>
  </div>

  <!-- Truth -->
  <div class="doc-section">
    <h2>The truth gate &amp; evals</h2>
    <p>Generated resumes and cover letters pass a <b>deterministic provenance gate</b> before they reach you: every claim must trace back to your master resume or your logged history, and the gate's check&rarr;revise loop verifies its own corrections. Edits to the master resume are audited, because the gate validates against it.</p>
    <p>Behind that sits a three-layer eval framework &mdash; deterministic checks, an adversarial LLM-as-judge calibrated against blind human labels, and a planted-error corpus with measured catch rates. Evals run nightly server-side, gate every cloud deploy, and are a product surface too: run the truth suite on your own applications and triage flagged claims from the dashboard.</p>
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
          <span>Cloud connector, desktop app, or mobile beta &mdash; connected in minutes.</span>
        </div>
      </a>
      <a class="doc-link" href="https://github.com/JustLikeFrank3/jobContextMCP/blob/main/docs/webmcp.md" target="_blank">
        <svg class="doc-link-icon" viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.8">
          <rect x="2" y="3" width="20" height="14" rx="2"/>
          <path d="M8 21h8M12 17v4"/>
        </svg>
        <div class="doc-link-text">
          <strong>WebMCP design notes</strong>
          <span>Bridge internals, security model, and browser enablement.</span>
        </div>
      </a>
      <a class="doc-link" href="https://github.com/JustLikeFrank3/jobContextMCP" target="_blank">
        <svg class="doc-link-icon" viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.8">
          <path d="M9 19c-4 1.3-4-2.2-6-2.7M15 21v-3.4a3 3 0 0 0-.8-2.3c2.8-.3 5.6-1.4 5.6-6a4.6 4.6 0 0 0-1.3-3.2 4.3 4.3 0 0 0-.1-3.2s-1-.3-3.4 1.3a11.6 11.6 0 0 0-6 0C6.6 1.6 5.6 1.9 5.6 1.9a4.3 4.3 0 0 0-.1 3.2A4.6 4.6 0 0 0 4.2 8.3c0 4.6 2.8 5.7 5.6 6a3 3 0 0 0-.8 2.3V21"/>
        </svg>
        <div class="doc-link-text">
          <strong>GitHub Repository</strong>
          <span>Full source, design docs, and incident post-mortems in PR history.</span>
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

<script src="https://cdn.jsdelivr.net/npm/mermaid@11.4.1/dist/mermaid.min.js"></script>
<script>
  /* Theme mermaid to the jobContext design tokens; if the CDN script failed
     to load, the raw diagram source stays visible as a code block. */
  if (window.mermaid) {
    mermaid.initialize({
      startOnLoad: true,
      sequence: { mirrorActors: false },
      theme: 'base',
      themeVariables: {
        darkMode: true,
        background: '#0F172A',
        primaryColor: '#16213A',
        primaryTextColor: '#F2F6FC',
        primaryBorderColor: '#2E4366',
        lineColor: '#64748B',
        secondaryColor: '#1B2A44',
        tertiaryColor: '#111A2B',
        clusterBkg: '#111A2B',
        clusterBorder: '#23324D',
        edgeLabelBackground: '#0F172A',
        fontFamily: "'Space Grotesk', system-ui, sans-serif",
        fontSize: '14px',
        actorBkg: '#16213A',
        actorBorder: '#2E4366',
        actorTextColor: '#F2F6FC',
        actorLineColor: '#64748B',
        signalColor: '#9AA8BF',
        signalTextColor: '#D7E3F8',
        noteBkgColor: '#1B2A44',
        noteTextColor: '#D7E3F8',
        noteBorderColor: '#2E4366'
      }
    });
  }
</script>

</body>
</html>
'''


def architecture_html() -> str:
    return ARCHITECTURE_HTML
