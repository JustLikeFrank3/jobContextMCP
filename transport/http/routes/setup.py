"""Public getting-started / Claude Desktop setup page (served at /setup).
Self-contained — design tokens + Google Fonts inlined, mirrors landing.py style.
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
.subtitle { font-size: 1.1rem; color: var(--muted); margin-bottom: 3rem; max-width: 600px; }

/* ---- Steps ---- */
.steps { display: flex; flex-direction: column; gap: 0; }
.step {
  display: flex; gap: 1.5rem; padding: 1.75rem 0;
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
      <svg viewBox="0 0 100 100" width="22" height="20" aria-label="jobContext">
        <circle cx="27" cy="21" r="7" fill="#fff"/>
        <path d="M27 31 L27 61 Q27 73 16 73" fill="none" stroke="#fff" stroke-width="9" stroke-linecap="round"/>
        <path d="M77 27 A24 24 0 1 0 77 67" fill="none" stroke="var(--cyan-500)" stroke-width="9" stroke-linecap="round"/>
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
  <h1>Set up jobContext with Claude Desktop</h1>
  <p class="subtitle">Five steps from zero to a fully connected AI memory layer for your job search. Takes about five minutes.</p>

  <div class="steps">

    <div class="step">
      <div class="step-num">1</div>
      <div class="step-body">
        <h3>Install Python 3</h3>
        <p>Open Terminal and check if Python is already installed:</p>
        <pre><code>python3 --version</code></pre>
        <p>If you see "command not found", download Python from <a href="https://python.org/downloads" target="_blank">python.org/downloads</a> and install it.</p>
      </div>
    </div>

    <div class="step">
      <div class="step-num">2</div>
      <div class="step-body">
        <h3>Clone the repo</h3>
        <pre><code>git clone https://github.com/JustLikeFrank3/jobContextMCP
cd jobContextMCP
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt</code></pre>
      </div>
    </div>

    <div class="step">
      <div class="step-num">3</div>
      <div class="step-body">
        <h3>Create your config file</h3>
        <pre><code>cp config.example.json config.json</code></pre>
        <p>Open <code>config.json</code> in any text editor. Fill in your name, email, phone, and LinkedIn. The <code>openai_api_key</code> field can be left blank for now &mdash; it is only needed for RAG search features, not tone samples or outreach.</p>
      </div>
    </div>

    <div class="step">
      <div class="step-num">4</div>
      <div class="step-body">
        <h3>Wire it to Claude Desktop</h3>
        <p>Make sure <a href="https://claude.ai/download" target="_blank">Claude Desktop</a> is installed, then open this file in a text editor (create it if it does not exist):</p>
        <p>
          <strong>Mac:</strong> <code>~/Library/Application Support/Claude/claude_desktop_config.json</code><br>
          <strong>Windows:</strong> <code>%APPDATA%\Claude\claude_desktop_config.json</code>
        </p>
        <p>Paste this, replacing the paths with wherever you cloned the repo:</p>
        <pre><code>{
  "mcpServers": {
    "jobContextMCP": {
      "command": "/absolute/path/to/jobContextMCP/.venv/bin/python3",
      "args": ["/absolute/path/to/jobContextMCP/server.py"],
      "cwd": "/absolute/path/to/jobContextMCP"
    }
  }
}</code></pre>
        <p>Example on Mac: <code>/Users/yourname/jobContextMCP/.venv/bin/python3</code></p>
      </div>
    </div>

    <div class="step">
      <div class="step-num">5</div>
      <div class="step-body">
        <h3>Bootstrap your workspace</h3>
        <p>Restart Claude Desktop. Then in a Claude chat, say:</p>
        <div class="note">"Run setup_workspace and walk me through it."</div>
        <p style="margin-top:.75rem">The tool will ask for your info and create all your data files from scratch.</p>
      </div>
    </div>

    <div class="step">
      <div class="step-num">&#43;</div>
      <div class="step-body">
        <h3>Add tone samples</h3>
        <p>Ask Claude to <code>log_tone_sample</code> from any message you write. After a few samples, <code>get_tone_profile</code> will reflect your voice and Claude can draft outreach in your register.</p>
        <div class="note"><strong>Note on work computers:</strong> IT restrictions may block running local scripts or modifying app config files. If you hit permission walls, Docker is the cleaner option. Check with IT first if unsure.</div>
      </div>
    </div>

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
          <strong>Remote &amp; Mobile Architecture</strong>
          <span>How jobContext exposes its tools over HTTP, SSE, and WebSocket for iPad and browser clients.</span>
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

  <div class="cta-band">
    <h2>Ready to connect?</h2>
    <p>Sign in to the hosted dashboard or run it locally.</p>
    <div class="cta-row">
      <a class="btn btn-primary" href="/login">Open dashboard</a>
      <a class="btn btn-ghost" href="https://github.com/JustLikeFrank3/jobContextMCP" target="_blank">View on GitHub</a>
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


def setup_html() -> str:
    return SETUP_HTML
