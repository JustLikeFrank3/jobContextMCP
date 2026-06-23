"""Shared HTML fragments reused across dashboard pages.

REDESIGNED by the jobContext Design System:
  - palette: teal #3FA8A8 -> brand cyan #06B6D4 on deep navy
  - type:    Inter -> Space Grotesk (loaded via @import in BASE_CSS)
  - logo:    new j+C mark (docs/branding/logo/jobcontextmcp-mark-dark.svg)
  - favicon: new j+C mark (no ASCII-$ binary motif)
Markup / class names are unchanged, so page modules need no edits.
"""
from __future__ import annotations

from .assets import logo_svg


def _auth_header_js() -> str:
  """Return dashboard fetch defaults.

  Browser dashboards now authenticate via the `jc_session` HTTP-only cookie
  set by /dashboard/login, so we intentionally do not expose API keys to
  client-side JavaScript.
  """
  return ''


BASE_CSS = """
  @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=JetBrains+Mono:wght@400;600&display=swap');
  :root {
    /* brand */
    --bg: #0a0f1c; --bg-2: #0b1220; --panel: #111a2b; --panel-2: #16213a;
    --muted: #9aa8bf; --faint: #6b7a93;
    --text: #f2f6fc; --text-soft: #d7e3f8;
    --accent: #06b6d4;            /* was #3FA8A8 teal — now brand cyan */
    --accent-bright: #22c7e0;
    --line: #23324d; --line-soft: #1a2740;
    --chip: #22324e; --well: #1b2a44;
    --danger: #ef4444; --ok: #22c55e; --warn: #f59e0b;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    background: linear-gradient(180deg, #0a0f1c 0%, #0b1220 100%);
    color: var(--text);
    font-family: 'Space Grotesk', ui-sans-serif, -apple-system, BlinkMacSystemFont,
                 Segoe UI, Roboto, Helvetica, Arial, sans-serif;
    -webkit-font-smoothing: antialiased;
  }
  .wrap { max-width: 1200px; margin: 0 auto; padding: 24px; }
  .header {
    display: flex; justify-content: space-between;
    align-items: center; margin-bottom: 18px; gap: 16px; flex-wrap: wrap;
  }
  .brand { display: flex; align-items: center; gap: 12px; }
  .brand-logo {
    width: 38px; height: 38px; border-radius: 9px;
    background: #0f172a; border: 1px solid var(--line);
    overflow: hidden; flex-shrink: 0;
  }
  .brand-logo svg { width: 38px; height: 38px; display: block; }
  h1 { margin: 0; font-size: 1.55rem; font-weight: 700; line-height: 1.15; letter-spacing: -0.02em; }
  .sub { color: var(--muted); font-size: 0.9rem; margin-top: 4px; }
  .pill {
    background: color-mix(in srgb, var(--accent) 14%, transparent);
    color: #6fe0ee;
    border: 1px solid color-mix(in srgb, var(--accent) 45%, transparent);
    padding: 5px 11px; border-radius: 999px;
    font-size: 0.72rem; font-weight: 600; white-space: nowrap;
  }
  nav.tabs { display: flex; gap: 6px; margin-bottom: 22px; flex-wrap: wrap; }
  nav.tabs a {
    padding: 7px 14px; border-radius: 8px; font-size: 0.85rem; font-weight: 500;
    text-decoration: none; color: var(--muted);
    border: 1px solid var(--line); background: var(--panel);
    white-space: nowrap;
    transition: color .15s, border-color .15s, background .15s;
  }
  nav.tabs a:hover { color: var(--text); border-color: var(--line); background: var(--panel-2); }
  nav.tabs a.active {
    color: #6fe0ee; font-weight: 600;
    border-color: color-mix(in srgb, var(--accent) 55%, transparent);
    background: color-mix(in srgb, var(--accent) 13%, transparent);
  }
  .cards {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
    gap: 10px; margin-bottom: 20px;
  }
  .card { background: var(--panel); border: 1px solid var(--line); border-radius: 12px; padding: 14px 16px; }
  .card .k { color: var(--muted); font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.08em; font-weight: 600; }
  .card .v { margin-top: 8px; font-size: 1.55rem; font-weight: 700; line-height: 1.1; }
  .card .v.warn { color: var(--warn); }
  .card .v.ok   { color: var(--ok); }
  .card .v.danger { color: var(--danger); }
  .logout-btn {
    background: none; border: 1px solid var(--line); border-radius: 8px;
    color: var(--muted); font-size: 0.8rem; font-family: inherit; padding: 7px 13px; cursor: pointer;
    transition: color .15s, border-color .15s, background .15s;
  }
  .logout-btn:hover { color: var(--text); border-color: var(--line); background: var(--panel-2); }
  .section-title { font-size: 1.2rem; font-weight: 600; color: var(--text-soft); letter-spacing: -0.01em; margin: 22px 0 12px; }
  .empty { color: var(--muted); border: 1px dashed var(--line); border-radius: 12px; padding: 24px; text-align: center; }
  .search {
    background: var(--well); color: var(--text);
    border: 1px solid var(--line); border-radius: 10px;
    padding: 10px 14px; font-size: 0.95rem; font-family: inherit; width: 100%;
  }
  .search:focus { outline: none; border-color: var(--accent); box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 30%, transparent); }
  /* primary action buttons, if present in pages */
  .btn-primary, button.primary {
    background: var(--accent); color: #062330; border: 1px solid transparent;
    border-radius: 8px; font-weight: 700; font-family: inherit; padding: 9px 16px; cursor: pointer;
    transition: background .12s;
  }
  .btn-primary:hover, button.primary:hover { background: var(--accent-bright); }
  code, pre, .mono { font-family: 'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, monospace; }
"""

# All pages that exist — used to render consistent nav
_PAGES = [
    ("Home",        "/dashboard",             "home"),
    ("Pipeline",    "/dashboard/pipeline",    "pipeline"),
    ("Job Hunt",    "/dashboard/job-hunt",    "job-hunt"),
    ("Materials",   "/dashboard/materials",   "materials"),
    ("Rejections",  "/dashboard/rejections",  "rejections"),
    ("Posts",       "/dashboard/posts",       "posts"),
    ("Outreach",    "/dashboard/people",      "people"),
    ("Wellbeing",   "/dashboard/health",      "health"),
    ("Digest",      "/dashboard/digest",      "digest"),
    ("Interviews",  "/dashboard/interviews",  "interviews"),
    ("API Keys",    "/dashboard/api-keys",    "api-keys"),
]


def nav_tabs(active: str) -> str:
  links = "\n    ".join(
    f'<a href="{href}"{active_attr}>{label}</a>'
    for label, href, key in _PAGES
    for active_attr in (" class=\"active\"" if key == active else "",)
  )
  return f'<nav class="tabs">\n    {links}\n  </nav>'


def page_header(title: str, subtitle: str = "") -> str:
    sub = f'<div class="sub">{subtitle}</div>' if subtitle else ""
    return f"""<header class="header">
    <div class="brand">
      <div class="brand-logo">{logo_svg()}</div>
      <div><h1>{title}</h1>{sub}</div>
    </div>
    <form method="post" action="/dashboard/logout" style="margin:0">
      <button class="logout-btn" type="submit">Sign out</button>
    </form>
  </header>"""


def html_page(title: str, active_tab: str, subtitle: str, extra_css: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>jobContext — {title}</title>
  <link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg%20xmlns='http://www.w3.org/2000/svg'%20viewBox='0%200%20100%20100'%20width='100'%20height='100'%3E%3Crect%20width='100'%20height='100'%20rx='20'%20fill='%230F172A'/%3E%3Cpath%20d='M70%2050%20A26%2026%200%201%200%2070%2076'%20fill='none'%20stroke='%2306B6D4'%20stroke-width='15'%20stroke-linecap='round'/%3E%3Ccircle%20cx='30'%20cy='26'%20r='9'%20fill='%23FFFFFF'/%3E%3Cpath%20d='M30%2039%20L30%2070%20Q30%2082%2017%2082'%20fill='none'%20stroke='%23FFFFFF'%20stroke-width='13'%20stroke-linecap='round'/%3E%3C/svg%3E" />
  <style>{BASE_CSS}{extra_css}</style>
  {_auth_header_js()}
</head>
<body>
<main class="wrap">
  {page_header(title, subtitle)}
  {nav_tabs(active_tab)}
  {body}
</main>
</body>
</html>"""
