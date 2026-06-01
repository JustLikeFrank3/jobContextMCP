"""Shared HTML fragments reused across dashboard pages."""
from __future__ import annotations

from .assets import logo_svg


BASE_CSS = """
  :root {
    --bg: #0b1220; --panel: #111a2b; --muted: #9aa8bf;
    --text: #e6edf7; --accent: #3FA8A8; --line: #23324d;
    --chip: #1a263c; --danger: #ef4444; --ok: #22c55e; --warn: #f59e0b;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    background: linear-gradient(180deg, #0b1220 0%, #0a1020 100%);
    color: var(--text);
    font-family: Inter, ui-sans-serif, -apple-system, BlinkMacSystemFont,
                 Segoe UI, Roboto, Helvetica, Arial, sans-serif;
  }
  .wrap { max-width: 1200px; margin: 0 auto; padding: 24px; }
  .header {
    display: flex; justify-content: space-between;
    align-items: center; margin-bottom: 18px; gap: 16px; flex-wrap: wrap;
  }
  .brand { display: flex; align-items: center; gap: 12px; }
  .brand-logo {
    width: 36px; height: 36px; border-radius: 8px;
    background: #1E1E1E; border: 1px solid var(--line);
    overflow: hidden; flex-shrink: 0;
  }
  .brand-logo svg { width: 36px; height: 36px; display: block; }
  h1 { margin: 0; font-size: 1.35rem; line-height: 1.2; letter-spacing: 0.2px; }
  .sub { color: var(--muted); font-size: 0.92rem; margin-top: 4px; }
  .pill {
    background: color-mix(in srgb, var(--accent) 18%, transparent);
    color: #d1fbfb;
    border: 1px solid color-mix(in srgb, var(--accent) 45%, transparent);
    padding: 6px 10px; border-radius: 999px;
    font-size: 0.78rem; font-weight: 600; white-space: nowrap;
  }
  nav.tabs { display: flex; gap: 6px; margin-bottom: 20px; flex-wrap: wrap; }
  nav.tabs a {
    padding: 7px 14px; border-radius: 8px; font-size: 0.85rem;
    text-decoration: none; color: var(--muted);
    border: 1px solid var(--line); background: var(--panel);
    transition: color .15s, border-color .15s;
  }
  nav.tabs a:hover { color: var(--text); border-color: var(--accent); }
  nav.tabs a.active {
    color: var(--accent); border-color: var(--accent);
    background: color-mix(in srgb, var(--accent) 10%, var(--panel));
  }
  .cards {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
    gap: 10px; margin-bottom: 20px;
  }
  .card { background: var(--panel); border: 1px solid var(--line); border-radius: 12px; padding: 14px; }
  .card .k { color: var(--muted); font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.45px; }
  .card .v { margin-top: 8px; font-size: 1.5rem; font-weight: 700; }
  .card .v.warn { color: var(--warn); }
  .card .v.ok   { color: var(--ok); }
  .card .v.danger { color: var(--danger); }
  .section-title { font-size: 0.96rem; color: #d7e3f8; letter-spacing: 0.25px; margin: 16px 0 10px; }
  .empty { color: var(--muted); border: 1px dashed var(--line); border-radius: 12px; padding: 20px; text-align: center; }
  .search {
    background: #0e1628; color: var(--text);
    border: 1px solid var(--line); border-radius: 10px;
    padding: 10px 12px; font-size: 0.92rem;
  }
"""

# All pages that exist — used to render consistent nav
_PAGES = [
    ("Home",        "/dashboard",             "home"),
    ("Job Hunt",    "/dashboard/job-hunt",    "job-hunt"),
    ("Materials",   "/dashboard/materials",   "materials"),
    ("Rejections",  "/dashboard/rejections",  "rejections"),
    ("Posts",       "/dashboard/posts",       "posts"),
    ("Outreach",    "/dashboard/people",      "people"),
    ("Wellbeing",   "/dashboard/health",      "health"),
]


def nav_tabs(active: str) -> str:
    links = "\n    ".join(
        f'<a href="{href}"{" class=\"active\"" if key == active else ""}>{label}</a>'
        for label, href, key in _PAGES
    )
    return f'<nav class="tabs">\n    {links}\n  </nav>'


def page_header(title: str, subtitle: str = "") -> str:
    sub = f'<div class="sub">{subtitle}</div>' if subtitle else ""
    return f"""<header class="header">
    <div class="brand">
      <div class="brand-logo">{logo_svg()}</div>
      <div><h1>{title}</h1>{sub}</div>
    </div>
    <span class="pill">feat/dashboard-ui</span>
  </header>"""


def html_page(title: str, active_tab: str, subtitle: str, extra_css: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>jobContextMCP — {title}</title>
  <style>{BASE_CSS}{extra_css}</style>
</head>
<body>
<main class="wrap">
  {page_header(title, subtitle)}
  {nav_tabs(active_tab)}
  {body}
</main>
</body>
</html>"""
