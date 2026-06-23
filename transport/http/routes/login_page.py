"""Branded sign-in page for jobContext.

Self-contained HTML (design tokens + Google Fonts inlined). Renders a
"Sign in with Microsoft" link to /dashboard/login (Entra PKCE) and a
"Request access" mailto link. Generated from the jobContext Design System.
"""
from __future__ import annotations

import html as _html

_LOGIN_TMPL: str = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Sign in — jobContext</title>
<style id="ds-tokens">
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500;600;700&display=swap');
/* ============================================================
   jobContext — Color tokens
   Redesign palette. Anchored on the brand sheet: deep navy ink,
   vivid cyan primary (#06B6D4), confirmation green (#22C55E,
   the "$" in the mark), warm slate neutrals, off-white text.
   The live dashboard's muted teal (#3FA8A8) is retired in favour
   of the brighter brand cyan; navy surfaces are kept and deepened.
   ============================================================ */
:root {
  /* ---- Ink / navy surface ramp (dark UI is the default) ---- */
  --ink-950: #070B14;   /* deepest backdrop / behind cards     */
  --ink-900: #0A0F1C;   /* app background (top of gradient)    */
  --ink-850: #0B1220;   /* app background (bottom of gradient) */
  --ink-800: #0F172A;   /* brand navy — hero / sidebar         */
  --ink-700: #111A2B;   /* panel / card surface                */
  --ink-600: #16213A;   /* raised panel / hover surface        */
  --ink-500: #1B2A44;   /* input wells, nested fills           */
  --ink-450: #22324E;   /* chip / tag fill                     */

  /* ---- Hairlines ---- */
  --line:      #23324D; /* default 1px border                  */
  --line-soft: #1A2740; /* quieter divider                     */
  --line-strong: #2E4366; /* emphasised border (active card)     */

  /* ---- Brand cyan (primary) ---- */
  --cyan-700: #0673a6;
  --cyan-600: #0894AE;
  --cyan-500: #06B6D4;  /* PRIMARY — actions, links, focus     */
  --cyan-400: #22C7E0;  /* hover / bright accent               */
  --cyan-300: #6FE0EE;  /* highlight text on dark              */
  --cyan-100: #D1FBFB;  /* faint cyan text                     */

  /* ---- Brand green (success / positive) ---- */
  --green-600: #16A34A;
  --green-500: #22C55E; /* success, positive deltas, "added"   */
  --green-300: #7BE6A4;

  /* ---- Slate neutral (from sheet #334155) ---- */
  --slate-700: #1E293B;
  --slate-600: #334155;
  --slate-400: #64748B;

  /* ---- Text ---- */
  --text:        #F2F6FC; /* primary text (near off-white)     */
  --text-strong: #FFFFFF; /* max-contrast headings             */
  --text-soft:   #D7E3F8; /* section titles                    */
  --muted:       #9AA8BF; /* secondary / labels                */
  --faint:       #6B7A93; /* tertiary / timestamps             */

  /* ---- Semantic status ---- */
  --danger: #EF4444;
  --danger-soft: #F87171;
  --warn:   #F59E0B;
  --ok:     #22C55E;
  --info:   #06B6D4;

  /* ============================================================
     Semantic aliases — prefer these in components
     ============================================================ */
  --bg-app:        var(--ink-900);
  --bg-app-2:      var(--ink-850);
  --surface:       var(--ink-700);
  --surface-raised:var(--ink-600);
  --surface-sunken:var(--ink-500);
  --surface-chip:  var(--ink-450);

  --border:        var(--line);
  --border-soft:   var(--line-soft);

  --primary:       var(--cyan-500);
  --primary-hover: var(--cyan-400);
  --primary-press: var(--cyan-600);
  --on-primary:    #062330;          /* dark ink on cyan buttons */

  --success:       var(--green-500);
  --on-success:    #052e16;

  --text-body:     var(--text);
  --text-heading:  var(--text-strong);
  --text-label:    var(--muted);

  --focus-ring:    color-mix(in srgb, var(--cyan-500) 55%, transparent);

  /* tints used for soft fills (pills, hover washes) */
  --tint-primary:  color-mix(in srgb, var(--cyan-500) 14%, transparent);
  --tint-primary-strong: color-mix(in srgb, var(--cyan-500) 22%, transparent);
  --tint-success:  color-mix(in srgb, var(--green-500) 16%, transparent);
  --tint-danger:   color-mix(in srgb, var(--danger) 16%, transparent);
  --tint-warn:     color-mix(in srgb, var(--warn) 16%, transparent);
}

/* ============================================================
   jobContext — Typography tokens
   Space Grotesk for everything in the UI (brand sheet: "Clean.
   Modern. Developer friendly."). JetBrains Mono for terminal-style
   surfaces (Daily Digest, code, API tokens, the binary motif).
   Note: Space Grotesk ships weights 300–700; --fw-extrabold maps
   to the 700 face.
   ============================================================ */
:root {
  /* ---- Families ---- */
  --font-display: 'Space Grotesk', ui-sans-serif, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
  --font-sans:    'Space Grotesk', ui-sans-serif, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
  --font-mono:    'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, Consolas, 'Liberation Mono', monospace;

  /* ---- Weights ---- */
  --fw-light:    300; /* @kind font */
  --fw-regular:  400; /* @kind font */
  --fw-medium:   500; /* @kind font */
  --fw-semibold: 600; /* @kind font */
  --fw-bold:     700; /* @kind font */
  --fw-extrabold:700; /* @kind font */

  /* ---- Type scale (rem, 16px base) ---- */
  --fs-display: 2.75rem;  /* 44px — hero numerals / marketing  */
  --fs-h1:      1.6rem;   /* 25.6px — page title               */
  --fs-h2:      1.2rem;   /* 19.2px — section / card heading   */
  --fs-h3:      1.0rem;   /* 16px — sub-heading                */
  --fs-stat:    1.55rem;  /* 24.8px — stat-card big number     */
  --fs-body:    0.95rem;  /* 15.2px — body / default UI text   */
  --fs-sm:      0.85rem;  /* 13.6px — secondary / nav          */
  --fs-xs:      0.78rem;  /* 12.5px — labels, chips            */
  --fs-2xs:     0.7rem;   /* 11.2px — eyebrow / uppercase key  */

  /* ---- Line heights ---- */
  --lh-tight:  1.15; /* @kind font */
  --lh-snug:   1.3;  /* @kind font */
  --lh-normal: 1.5;  /* @kind font */
  --lh-relaxed:1.65; /* @kind font */

  /* ---- Letter spacing ---- */
  --ls-tight:  -0.02em; /* @kind font */
  --ls-normal: 0;       /* @kind font */
  --ls-label:  0.04em;  /* @kind font */
  --ls-eyebrow:0.08em;  /* @kind font */

  /* ---- Semantic text roles ---- */
  --text-page-title:  var(--fw-bold) var(--fs-h1)/var(--lh-tight) var(--font-display);
  --text-section:     var(--fw-semibold) var(--fs-h2)/var(--lh-snug) var(--font-display);
  --text-stat:        var(--fw-bold) var(--fs-stat)/1.1 var(--font-display);
  --text-eyebrow-ls:  var(--ls-eyebrow);
}

/* Uppercase eyebrow / key label helper (used on stat cards) */
.jc-eyebrow {
  font: var(--fw-semibold) var(--fs-2xs)/1.2 var(--font-sans);
  text-transform: uppercase;
  letter-spacing: var(--ls-eyebrow);
  color: var(--muted);
}

/* ============================================================
   jobContext — Spacing, radius, shadow, motion tokens
   ============================================================ */
:root {
  /* ---- Spacing scale (4px base) ---- */
  --space-0:  0;
  --space-1:  4px;
  --space-2:  8px;
  --space-3:  12px;
  --space-4:  16px;
  --space-5:  20px;
  --space-6:  24px;
  --space-8:  32px;
  --space-10: 40px;
  --space-12: 48px;
  --space-16: 64px;

  /* ---- Layout ---- */
  --wrap-max: 1200px;     /* dashboard content column          */
  --page-pad: 24px;

  /* ---- Radii ---- */
  --radius-xs:  6px;      /* chips, small inputs               */
  --radius-sm:  8px;      /* buttons, nav tabs                 */
  --radius-md:  10px;     /* inputs, search                    */
  --radius-lg:  12px;     /* cards / panels                    */
  --radius-xl:  14px;     /* hero cards, modals                */
  --radius-pill:999px;    /* pills, status badges, avatars     */

  /* ---- Borders ---- */
  --border-w: 1px;

  /* ---- Shadows (subtle; dark UI leans on borders, not blur) */
  --shadow-sm: 0 1px 2px rgba(0,0,0,0.30);
  --shadow-md: 0 6px 20px rgba(0,0,0,0.35);
  --shadow-lg: 0 18px 50px rgba(0,0,0,0.45);
  /* cyan glow for primary/active emphasis */
  --glow-primary: 0 0 0 1px color-mix(in srgb, var(--cyan-500) 50%, transparent),
                  0 8px 30px color-mix(in srgb, var(--cyan-500) 18%, transparent);

  /* ---- Motion ---- */
  --ease-out: cubic-bezier(0.16, 1, 0.3, 1); /* @kind other */
  --ease-std: cubic-bezier(0.4, 0, 0.2, 1);  /* @kind other */
  --dur-fast: 120ms; /* @kind other */
  --dur-base: 160ms; /* @kind other */
  --dur-slow: 240ms; /* @kind other */
}

</style>
<style>
  * { box-sizing: border-box; }
  body { margin: 0; min-height: 100vh; background: var(--bg-app); color: var(--text); font-family: var(--font-sans); -webkit-font-smoothing: antialiased; }
  a { color: inherit; text-decoration: none; }
  .split { display: grid; grid-template-columns: 1.05fr 0.95fr; min-height: 100vh; }

  /* ---- left brand panel ---- */
  .panel { position: relative; overflow: hidden; background: linear-gradient(165deg, var(--ink-900) 0%, var(--ink-850) 100%); border-right: 1px solid var(--border-soft); padding: 48px 56px; display: flex; flex-direction: column; justify-content: space-between; }
  .panel::before { content: ""; position: absolute; inset: 0; background: radial-gradient(560px 360px at 88% 6%, color-mix(in srgb, var(--cyan-500) 14%, transparent), transparent 70%), radial-gradient(460px 300px at 0% 100%, color-mix(in srgb, var(--cyan-700) 12%, transparent), transparent 70%); pointer-events: none; }
  .brand { position: relative; display: flex; align-items: center; gap: 11px; }
  .wm { font-family: var(--font-display); font-weight: 700; font-size: 1.3rem; letter-spacing: -0.02em; color: #fff; }
  .wm .c { color: var(--cyan-400); }
  .panel-mid { position: relative; max-width: 30rem; }
  .panel-mid h2 { font-family: var(--font-display); font-weight: 700; font-size: 2.4rem; line-height: 1.1; letter-spacing: -0.025em; color: #fff; margin: 0; text-wrap: balance; }
  .panel-mid h2 .c { color: var(--cyan-400); }
  .panel-mid p { color: var(--muted); font-size: 1.05rem; line-height: 1.6; margin: 18px 0 0; }
  .blist { position: relative; display: flex; flex-direction: column; gap: 14px; margin-top: 30px; }
  .blist .row { display: flex; align-items: center; gap: 12px; color: var(--text-soft); font-size: var(--fs-sm); }
  .blist .ic { width: 30px; height: 30px; border-radius: var(--radius-sm); background: var(--tint-primary); border: 1px solid color-mix(in srgb, var(--cyan-500) 30%, transparent); display: flex; align-items: center; justify-content: center; color: var(--cyan-300); flex-shrink: 0; }
  .blist .ic svg { width: 16px; height: 16px; }
  .panel-foot { position: relative; color: var(--faint); font-size: var(--fs-xs); font-family: var(--font-mono); }

  /* ---- right form ---- */
  .formside { display: grid; place-items: center; padding: 40px 24px; }
  .card { width: 100%; max-width: 384px; }
  .card .lead { font-family: var(--font-display); font-weight: 700; font-size: 1.7rem; letter-spacing: -0.02em; color: #fff; margin: 0; }
  .card .leadsub { color: var(--muted); font-size: var(--fs-sm); margin: 8px 0 28px; line-height: 1.5; }
  label { display: block; font-size: var(--fs-xs); font-weight: 600; color: var(--muted); margin: 0 0 8px; }
  .field { position: relative; margin-bottom: 18px; }
  .field input { width: 100%; background: var(--surface-sunken); color: var(--text); border: 1px solid var(--border); border-radius: var(--radius-md); padding: 12px 14px; font-size: var(--fs-body); font-family: var(--font-sans); transition: border-color .15s, box-shadow .15s; }
  .field input::placeholder { color: var(--faint); }
  .field input:focus { outline: none; border-color: var(--primary); box-shadow: 0 0 0 3px var(--focus-ring); }
  button.submit { width: 100%; border: 0; border-radius: var(--radius-md); padding: 12px 16px; background: var(--primary); color: var(--on-primary); font-family: var(--font-sans); font-weight: 700; font-size: var(--fs-body); cursor: pointer; transition: background .14s, transform .12s; }
  button.submit:hover { background: var(--primary-hover); }
  button.submit:active { transform: translateY(0.5px) scale(0.995); }
  .hint { margin-top: 16px; display: flex; align-items: flex-start; gap: 8px; color: var(--faint); font-size: var(--fs-xs); line-height: 1.5; }
  .hint svg { width: 14px; height: 14px; color: var(--green-500); flex-shrink: 0; margin-top: 1px; }
  .back { display: inline-flex; align-items: center; gap: 6px; margin-top: 26px; color: var(--muted); font-size: var(--fs-sm); transition: color .15s; }
  .back:hover { color: var(--cyan-300); }

  @media (max-width: 860px) {
    .split { grid-template-columns: 1fr; }
    .panel { display: none; }
  }
</style>
</head>
<body>
<div class="split">

  <!-- brand / value panel -->
  <aside class="panel">
    <a class="brand" href="/">
      <svg viewBox="0 0 320 290" width="32" height="29" aria-label="jobContext">
        <path d="M268.2 124.5 A80 80 0 1 0 268.2 175.5" fill="none" stroke="var(--cyan-500)" stroke-width="46" stroke-linecap="round"/>
        <circle cx="84" cy="54" r="27" fill="#fff"/>
        <path d="M84 98 L84 207 Q84 250 41 250" fill="none" stroke="#fff" stroke-width="40" stroke-linecap="round"/>
      </svg>
      <span class="wm">job<span class="c">Context</span></span>
    </a>

    <div class="panel-mid">
      <h2>Welcome back to your <span class="c">career memory.</span></h2>
      <p>Every application, contact, post, and interview — remembered and ready for any AI assistant.</p>
      <div class="blist">
        <div class="row"><span class="ic"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l7 3v5c0 4.4-3 7.6-7 9-4-1.4-7-4.6-7-9V6l7-3z"/><path d="M9 12l2 2 4-4"/></svg></span>Self-hosted &amp; private — your data never leaves your server</div>
        <div class="row"><span class="ic"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M7 18a4 4 0 010-8 5 5 0 019.6-1.3A3.5 3.5 0 0117 18H7z"/></svg></span>Works with Claude, Copilot, Cursor, Windsurf &amp; Zed</div>
        <div class="row"><span class="ic"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M3 5h14M3 10h10M3 15h6"/></svg></span>70+ tools across 11 career surfaces</div>
      </div>
    </div>

    <div class="panel-foot">Your career has context. Your AI should too.</div>
  </aside>

  <!-- sign-in form -->
  <main class="formside">
    <div class="card">
      <h1 class="lead">Sign in</h1>
      <p class="leadsub">jobContext uses Microsoft sign-in. If you have received an invitation, click below to continue.</p>
      <a class="submit" href="/dashboard/login?next=__NEXT_HREF__" style="display:block;text-align:center;text-decoration:none;border-radius:var(--radius-md);padding:12px 16px;background:var(--primary);color:var(--on-primary);font-family:var(--font-sans);font-weight:700;font-size:var(--fs-body);">
        Sign in with Microsoft
      </a>
      <div class="hint" style="margin-top:20px;">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V7a4 4 0 018 0v4"/></svg>
        You must have a valid invitation to sign in.
      </div>
      <div class="hint" style="margin-top:12px;border-top:1px solid rgba(255,255,255,0.08);padding-top:14px;">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 4h16v16H4z" rx="2"/><path d="M22 6l-10 7L2 6"/></svg>
        No invitation yet?
        <a href="mailto:jobContextMCP@gmail.com?subject=Access%20Request%20%E2%80%94%20jobContext&body=Hi%2C%0A%0AI%27d%20love%20to%20try%20jobContext.%20Here%27s%20a%20bit%20about%20me%3A%0A%0A" style="color:var(--primary);text-decoration:none;font-weight:600;">Request access</a>
      </div>
      <a class="back" href="/">
        <svg viewBox="0 0 20 20" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M11 5l-5 5 5 5"/></svg>
        Back to home
      </a>
    </div>
  </main>

</div>
</body>
</html>
'''


def login_html(next_url: str = "/dashboard") -> str:
    """Return the branded sign-in page with next_url URL-encoded into the Microsoft sign-in link."""
    from urllib.parse import quote as _quote
    safe_href = _quote(next_url, safe="")
    safe_html = _html.escape(next_url, quote=True)
    return _LOGIN_TMPL.replace("__NEXT_HREF__", safe_href).replace("__NEXT__", safe_html)
