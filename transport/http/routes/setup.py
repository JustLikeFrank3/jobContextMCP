"""Public getting-started page (served at /setup).
Self-contained — design tokens + Google Fonts inlined, mirrors landing.py style.
Covers the three onboarding paths: cloud connector, desktop app, mobile beta.
"""
from __future__ import annotations

SETUP_HTML: str = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Get started &mdash; jobContext</title>
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
/* scroll-padding-top keeps anchored headings clear of the 54px sticky nav */
html { font-size: 16px; scroll-behavior: smooth; scroll-padding-top: 78px; }
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
  border-bottom: 1px solid var(--line);
  padding: 0 1.5rem;
}
.nav-inner {
  max-width: 860px; margin: 0 auto;
  display: flex; align-items: center; justify-content: space-between;
  height: 54px;
}
.brand { display: flex; align-items: center; gap: .5rem; font-weight: 600; color: var(--text-strong); }
.brand .c { color: var(--cyan-500); }
.nav-links { display: flex; gap: 1.5rem; font-size: .875rem; }
.nav-links a { color: var(--muted); }
.nav-links a:hover { color: var(--text); text-decoration: none; }

/* ---- Content ---- */
.wrap { max-width: 860px; margin: 0 auto; padding: 3rem 1.5rem 5rem; }
.page-eyebrow {
  font-size: .75rem; font-weight: 600; letter-spacing: .12em;
  text-transform: uppercase; color: var(--cyan-500); margin-bottom: .75rem;
}
h1 { font-size: 2.2rem; font-weight: 700; color: var(--text-strong); line-height: 1.15; margin-bottom: 1rem; }
.subtitle { font-size: 1.1rem; color: var(--muted); margin-bottom: 2.5rem; max-width: 640px; }

/* ---- Path chooser ---- */
.chooser { display: grid; grid-template-columns: repeat(3, 1fr); gap: .75rem; margin-bottom: 3rem; }
.choice {
  display: block; background: var(--ink-700); border: 1px solid var(--line);
  border-radius: 10px; padding: 1.1rem 1.2rem; text-decoration: none;
  transition: border-color .15s;
}
.choice:hover { border-color: var(--cyan-500); text-decoration: none; }
.choice .k {
  font-family: var(--font-mono); font-size: .7rem; font-weight: 700;
  color: var(--cyan-400); text-transform: uppercase; letter-spacing: .06em;
}
.choice strong { display: block; color: var(--text-strong); font-size: .95rem; margin-top: .35rem; }
.choice span { display: block; color: var(--muted); font-size: .825rem; margin-top: .2rem; }
@media (max-width: 640px) { .chooser { grid-template-columns: 1fr; } }

/* ---- Path sections ---- */
.path { margin-bottom: 3rem; }
.path > h2 {
  font-size: 1.35rem; font-weight: 700; color: var(--text-strong);
  padding-bottom: .5rem; border-bottom: 1px solid var(--line); margin-bottom: .35rem;
}
.path > .path-sub { color: var(--muted); font-size: .95rem; margin-bottom: .5rem; }

/* ---- Steps ---- */
.steps { display: flex; flex-direction: column; gap: 0; }
.step {
  display: flex; gap: 1.5rem; padding: 1.5rem 0;
  border-bottom: 1px solid var(--line-soft);
}
.step:last-child { border-bottom: none; }
.step-num {
  flex-shrink: 0; width: 36px; height: 36px;
  border-radius: 50%; background: var(--ink-600); border: 1px solid var(--line-strong);
  display: flex; align-items: center; justify-content: center;
  font-size: .85rem; font-weight: 700; color: var(--cyan-500); margin-top: .15rem;
}
.step-body h3 { font-size: 1.05rem; font-weight: 600; color: var(--text-strong); margin-bottom: .4rem; }
.step-body p { color: var(--muted); font-size: .95rem; margin-bottom: .75rem; }
.step-body p:last-child { margin-bottom: 0; }
.note {
  background: var(--ink-600); border: 1px solid var(--line);
  border-left: 3px solid var(--cyan-500);
  border-radius: 6px; padding: .75rem 1rem;
  font-size: .875rem; color: var(--text-soft); margin-top: .75rem;
}
code, pre {
  font-family: var(--font-mono); font-size: .875rem;
}
code {
  background: var(--ink-500); border: 1px solid var(--line);
  padding: .15em .4em; border-radius: 4px; color: var(--cyan-300);
}
pre {
  background: var(--ink-800); border: 1px solid var(--line);
  border-radius: 8px; padding: 1rem 1.25rem; overflow-x: auto;
  color: var(--text-soft); line-height: 1.5; margin: .75rem 0;
}
pre code { background: none; border: none; padding: 0; color: inherit; }

/* ---- See also ---- */
.see-also {
  margin-top: 3.5rem; padding: 1.5rem;
  background: var(--ink-700); border: 1px solid var(--line);
  border-radius: 10px;
}
.see-also h4 { font-size: .75rem; font-weight: 600; letter-spacing: .1em;
  text-transform: uppercase; color: var(--muted); margin-bottom: 1rem; }
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

/* ---- CTA ---- */
.cta-band {
  margin-top: 3.5rem; padding: 2rem; text-align: center;
  background: linear-gradient(135deg, var(--ink-700) 0%, var(--ink-600) 100%);
  border: 1px solid var(--line-strong); border-radius: 12px;
}
.cta-band h2 { font-size: 1.5rem; font-weight: 700; color: var(--text-strong); margin-bottom: .5rem; }
.cta-band p { color: var(--muted); margin-bottom: 1.25rem; }
.btn {
  display: inline-flex; align-items: center; gap: .5rem;
  padding: .65rem 1.4rem; border-radius: 8px; font-weight: 600; font-size: .95rem;
  text-decoration: none; transition: all .15s;
}
.btn-primary { background: var(--cyan-500); color: #000; }
.btn-primary:hover { background: var(--cyan-400); text-decoration: none; color: #000; }
.btn-ghost { border: 1px solid var(--line-strong); color: var(--text-soft); }
.btn-ghost:hover { border-color: var(--cyan-500); color: var(--text); text-decoration: none; }
.cta-row { display: flex; gap: .75rem; justify-content: center; flex-wrap: wrap; }

/* ---- Footer ---- */
footer { border-top: 1px solid var(--line); padding: 1.5rem; }
.foot-inner {
  max-width: 860px; margin: 0 auto;
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
      <a href="/architecture">Architecture</a>
      <a href="/login">Sign in</a>
    </div>
  </div>
</nav>

<div class="wrap">
  <div class="page-eyebrow">Getting started</div>
  <h1>Get started with jobContext</h1>
  <p class="subtitle">Three ways in, all backed by the same memory. Pick the one that fits how you work; you can add the others later, and everything stays in sync.</p>

  <div class="chooser">
    <a class="choice" href="#cloud">
      <span class="k">Fastest</span>
      <strong>Cloud + your AI</strong>
      <span>Sign in, add a connector. About a minute.</span>
    </a>
    <a class="choice" href="#desktop">
      <span class="k">Most private</span>
      <strong>Desktop app</strong>
      <span>Native app, local data, no account.</span>
    </a>
    <a class="choice" href="#mobile">
      <span class="k">Companion</span>
      <strong>Mobile (iOS beta)</strong>
      <span>Capture jobs from your phone's share sheet.</span>
    </a>
  </div>

  <!-- ============ CLOUD ============ -->
  <div class="path" id="cloud">
    <h2>Cloud: connect your AI in about a minute</h2>
    <p class="path-sub">The hosted workspace at jobcontext.ai. No installs, no config files, no infrastructure.</p>
    <div class="steps">

      <div class="step">
        <div class="step-num">1</div>
        <div class="step-body">
          <h3>Sign in with Microsoft</h3>
          <p><a href="/login">Sign in</a> with any Microsoft account. Your private, isolated workspace is created on first login; nobody else's data touches yours.</p>
        </div>
      </div>

      <div class="step">
        <div class="step-num">2</div>
        <div class="step-body">
          <h3>Add the connector to your AI client</h3>
          <p>In Claude.ai, Cursor, or VS Code, add a remote MCP server pointing at:</p>
          <pre><code>https://jobcontext.ai/mcp</code></pre>
          <p>Your client opens a sign-in window and OAuth handles the rest: no keys to copy, no JSON to edit. The client discovers all 12 domain tools automatically.</p>
        </div>
      </div>

      <div class="step">
        <div class="step-num">3</div>
        <div class="step-body">
          <h3>Or skip the connector entirely: WebMCP</h3>
          <p>The dashboard is itself an agent surface. Open it in ChatGPT desktop's built-in browser while signed in and the in-page agent discovers every tool via <code>document.modelContext</code>, with no setup at all. Chrome (behind an origin trial) and Edge's preview gain the same tools as their WebMCP support lands.</p>
        </div>
      </div>

      <div class="step">
        <div class="step-num">4</div>
        <div class="step-body">
          <h3>Bootstrap your workspace</h3>
          <p>In your AI chat, say:</p>
          <div class="note">"Run workspace setup and walk me through it."</div>
          <p style="margin-top:.75rem">The <code>workspace</code> tool creates your whole data tree with zero manual setup. Then drop in your resume and start talking: log contacts, assess postings, generate documents. It remembers all of it next session.</p>
        </div>
      </div>

    </div>
  </div>

  <!-- ============ DESKTOP ============ -->
  <div class="path" id="desktop">
    <h2>Desktop: the whole platform as a native app</h2>
    <p class="path-sub">No terminal, no Python, no account. Local SQLite; everything stays on your machine.</p>
    <div class="steps">

      <div class="step">
        <div class="step-num">1</div>
        <div class="step-body">
          <h3>Download and install</h3>
          <p>Grab the newest <code>desktop-v*</code> build from the <a href="https://github.com/JustLikeFrank3/jobContextMCP/releases?q=desktop&expanded=true" target="_blank">releases page</a>: a signed &amp; notarized <code>.dmg</code> for macOS (Apple Silicon and Intel), an Authenticode-signed installer for Windows, and <code>.AppImage</code>/<code>.deb</code> for Linux. Updates install themselves.</p>
        </div>
      </div>

      <div class="step">
        <div class="step-num">2</div>
        <div class="step-body">
          <h3>Open it. That's the setup</h3>
          <p>The app runs the full server locally and opens the same dashboard the cloud serves. Chat with an embedded AI over your own data: bring your own OpenAI or Anthropic key, or point it at a local Ollama model and run with no keys and no cloud at all.</p>
        </div>
      </div>

      <div class="step">
        <div class="step-num">3</div>
        <div class="step-body">
          <h3>Optional: connect clients and sync</h3>
          <p><strong>One-click MCP connect</strong> wires Claude Desktop, VS Code, or Cursor to your local server from the Settings screen. Link your cloud workspace and desktop &#8646; cloud sync keeps both sides current and feeds the mobile app.</p>
        </div>
      </div>

    </div>
  </div>

  <!-- ============ MOBILE ============ -->
  <div class="path" id="mobile">
    <h2>Mobile: capture from your phone</h2>
    <p class="path-sub">The iOS companion, in TestFlight beta. Desktop creates knowledge; mobile captures reality.</p>
    <div class="steps">

      <div class="step">
        <div class="step-num">1</div>
        <div class="step-body">
          <h3>Join the beta</h3>
          <p>The app is in TestFlight; see <a href="https://github.com/JustLikeFrank3/jobContextMCP/blob/main/mobile/README.md" target="_blank">mobile/README.md</a> for the current beta link and screens.</p>
        </div>
      </div>

      <div class="step">
        <div class="step-num">2</div>
        <div class="step-body">
          <h3>Paste an API key</h3>
          <p>Create a personal access token on the dashboard's <strong>API Keys</strong> tab, paste it once into the app's Settings, and it lives in your device keychain. No separate sign-in to go stale while the app sits unopened.</p>
        </div>
      </div>

      <div class="step">
        <div class="step-num">3</div>
        <div class="step-body">
          <h3>Share postings straight into your pipeline</h3>
          <p>See a role in Safari or LinkedIn? Share it to jobContext. Pages are extracted <em>on your phone</em>, so it reads postings that block datacenter IPs. Triage the queue and log wellbeing check-ins from anywhere; everything syncs back to desktop and cloud.</p>
        </div>
      </div>

    </div>
  </div>

  <!-- ============ SELF-HOST ============ -->
  <div class="path" id="selfhost">
    <h2>Prefer to run it yourself?</h2>
    <p class="path-sub">It's open source (MIT). Clone, create a venv, and run: stdio MCP for local clients or the full HTTP server with the dashboard.</p>
    <pre><code>git clone https://github.com/JustLikeFrank3/jobContextMCP
cd jobContextMCP
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python server.py          # stdio MCP server
# or the HTTP server: dashboard + REST + MCP Streamable HTTP at /mcp</code></pre>
    <p style="color:var(--muted); font-size:.95rem">Per-client walkthroughs (VS Code, Claude Desktop, ChatGPT desktop, Cursor, Windsurf), Docker mode, and deployment guides live in the repo: <a href="https://github.com/JustLikeFrank3/jobContextMCP/blob/main/docs/client-setup.md" target="_blank">docs/client-setup.md</a> and <a href="https://github.com/JustLikeFrank3/jobContextMCP/blob/main/docs/local-development.md" target="_blank">docs/local-development.md</a>.</p>
  </div>

  <!-- See also -->
  <div class="see-also">
    <h4>See also</h4>
    <div class="doc-links">
      <a class="doc-link" href="/architecture">
        <svg class="doc-link-icon" viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.8">
          <rect x="2" y="3" width="20" height="14" rx="2"/>
          <path d="M8 21h8M12 17v4"/>
        </svg>
        <div class="doc-link-text">
          <strong>Architecture</strong>
          <span>One capability layer behind MCP, WebMCP, HTTP, desktop, and mobile.</span>
        </div>
      </a>
      <a class="doc-link" href="https://github.com/JustLikeFrank3/jobContextMCP" target="_blank">
        <svg class="doc-link-icon" viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.8">
          <path d="M9 19c-4 1.3-4-2.2-6-2.7M15 21v-3.4a3 3 0 0 0-.8-2.3c2.8-.3 5.6-1.4 5.6-6a4.6 4.6 0 0 0-1.3-3.2 4.3 4.3 0 0 0-.1-3.2s-1-.3-3.4 1.3a11.6 11.6 0 0 0-6 0C6.6 1.6 5.6 1.9 5.6 1.9a4.3 4.3 0 0 0-.1 3.2A4.6 4.6 0 0 0 4.2 8.3c0 4.6 2.8 5.7 5.6 6a3 3 0 0 0-.8 2.3V21"/>
        </svg>
        <div class="doc-link-text">
          <strong>GitHub Repository</strong>
          <span>Full source code, docs, issues, and contribution guides.</span>
        </div>
      </a>
    </div>
  </div>

  <div class="cta-band">
    <h2>Ready to connect?</h2>
    <p>Sign in to the hosted dashboard, or download the desktop app and keep it all local.</p>
    <div class="cta-row">
      <a class="btn btn-primary" href="/login">Open dashboard</a>
      <a class="btn btn-ghost" href="https://github.com/JustLikeFrank3/jobContextMCP/releases?q=desktop&expanded=true" target="_blank">Download desktop</a>
    </div>
  </div>
</div>

<footer>
  <div class="foot-inner">
    <span class="muted">&copy; 2026 jobContext &middot; The memory layer for your career.</span>
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


def setup_html() -> str:
    return SETUP_HTML
