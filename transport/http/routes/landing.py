"""Public marketing landing page for jobContext (served at /). Self-contained — tokens + Google Fonts inlined. Generated from the jobContext Design System."""
from __future__ import annotations

LANDING_HTML: str = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>jobContext &mdash; The memory layer for your career</title>
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
  html { scroll-behavior: smooth; }
  body {
    margin: 0;
    background: var(--bg-app);
    color: var(--text);
    font-family: var(--font-sans);
    -webkit-font-smoothing: antialiased;
    line-height: 1.5;
  }
  a { color: inherit; text-decoration: none; }
  .wrap { max-width: 1120px; margin: 0 auto; padding: 0 32px; }

  /* ---------- top nav ---------- */
  .nav {
    position: sticky; top: 0; z-index: 50;
    background: color-mix(in srgb, var(--ink-900) 82%, transparent);
    backdrop-filter: blur(12px);
    border-bottom: 1px solid var(--border-soft);
  }
  .nav-inner { display: flex; align-items: center; justify-content: space-between; height: 66px; }
  .nav-links { display: flex; align-items: center; gap: 28px; }
  .nav-links a.lnk { font-size: var(--fs-sm); color: var(--muted); transition: color .15s; }
  .nav-links a.lnk:hover { color: var(--text); }
  .brand { display: flex; align-items: center; gap: 11px; }
  .wm { font-family: var(--font-display); font-weight: 700; font-size: 1.32rem; letter-spacing: -0.02em; color: #fff; }
  .wm .c { color: var(--cyan-400); }

  .btn { display: inline-flex; align-items: center; gap: 8px; border-radius: var(--radius-sm); font-family: var(--font-sans); font-weight: 600; cursor: pointer; transition: background .14s, border-color .14s, color .14s, transform .14s; white-space: nowrap; }
  .btn-primary { background: var(--primary); color: var(--on-primary); border: 1px solid transparent; font-weight: 700; padding: 10px 18px; font-size: var(--fs-sm); }
  .btn-primary:hover { background: var(--primary-hover); }
  .btn-primary:active { transform: translateY(0.5px) scale(0.99); }
  .btn-ghost { background: transparent; color: var(--text); border: 1px solid var(--border); padding: 9px 16px; font-size: var(--fs-sm); }
  .btn-ghost:hover { border-color: var(--primary); }
  .btn-lg { padding: 13px 24px; font-size: var(--fs-body); border-radius: var(--radius-md); }

  /* ---------- hero ---------- */
  .hero { position: relative; overflow: hidden; padding: 84px 0 72px; }
  .hero::before {
    content: ""; position: absolute; inset: 0;
    background:
      radial-gradient(620px 360px at 78% 8%, color-mix(in srgb, var(--cyan-500) 13%, transparent), transparent 70%),
      radial-gradient(520px 320px at 8% 92%, color-mix(in srgb, var(--cyan-700) 10%, transparent), transparent 70%);
    pointer-events: none;
  }
  .hero-grid { position: relative; display: grid; grid-template-columns: 1.04fr 0.96fr; gap: 56px; align-items: center; }
  .eyebrow { display: inline-flex; align-items: center; gap: 9px; padding: 6px 13px; border-radius: var(--radius-pill); background: var(--tint-primary); border: 1px solid color-mix(in srgb, var(--cyan-500) 40%, transparent); color: var(--cyan-300); font-size: var(--fs-2xs); font-weight: 600; letter-spacing: 0.02em; }
  .eyebrow .dot { width: 6px; height: 6px; border-radius: 50%; background: var(--green-500); box-shadow: 0 0 0 3px color-mix(in srgb, var(--green-500) 25%, transparent); }
  h1.hl { font-family: var(--font-display); font-weight: 700; font-size: 3.5rem; line-height: 1.04; letter-spacing: -0.03em; margin: 22px 0 0; color: #fff; text-wrap: balance; }
  h1.hl .c { color: var(--cyan-400); }
  .lede { color: var(--muted); font-size: 1.18rem; line-height: 1.6; margin: 22px 0 0; max-width: 30em; text-wrap: pretty; }
  .cta-row { display: flex; gap: 12px; margin-top: 32px; flex-wrap: wrap; }
  .micro { margin-top: 18px; color: var(--faint); font-size: var(--fs-xs); display: flex; gap: 18px; flex-wrap: wrap; }
  .micro span { display: inline-flex; align-items: center; gap: 7px; }
  .micro svg { width: 15px; height: 15px; color: var(--green-500); }

  /* hero visual — terminal card */
  .term { background: var(--ink-950); border: 1px solid var(--border); border-radius: var(--radius-xl); box-shadow: var(--shadow-lg); overflow: hidden; }
  .term-bar { display: flex; align-items: center; gap: 7px; padding: 12px 15px; border-bottom: 1px solid var(--border-soft); background: var(--ink-900); }
  .term-bar i { width: 11px; height: 11px; border-radius: 50%; display: block; }
  .term-title { margin-left: 10px; font-family: var(--font-mono); font-size: var(--fs-2xs); color: var(--faint); }
  .term-body { padding: 18px 19px; font-family: var(--font-mono); font-size: 13.2px; line-height: 1.85; }
  .term-body .u { color: var(--text-soft); }
  .term-body .p { color: var(--cyan-300); }
  .term-body .g { color: var(--faint); }
  .term-body .ok { color: var(--green-300); }
  .term-body .hl2 { color: #fff; }
  .term-body .tool { color: var(--cyan-400); }

  /* ---------- logos strip ---------- */
  .strip { border-top: 1px solid var(--border-soft); border-bottom: 1px solid var(--border-soft); padding: 26px 0; }
  .strip-inner { display: flex; align-items: center; gap: 14px 40px; flex-wrap: wrap; justify-content: center; }
  .strip .lbl { color: var(--faint); font-size: var(--fs-xs); }
  .strip .name { color: var(--muted); font-weight: 600; font-size: var(--fs-sm); letter-spacing: 0.01em; }

  /* ---------- sections ---------- */
  section.blk { padding: 88px 0; }
  .sec-head { max-width: 640px; margin: 0 auto 52px; text-align: center; }
  .sec-eyebrow { color: var(--cyan-400); font-size: var(--fs-xs); font-weight: 700; text-transform: uppercase; letter-spacing: var(--ls-eyebrow); }
  .sec-head h2 { font-family: var(--font-display); font-weight: 700; font-size: 2.3rem; letter-spacing: -0.02em; line-height: 1.12; margin: 12px 0 0; color: #fff; text-wrap: balance; }
  .sec-head p { color: var(--muted); font-size: 1.06rem; margin: 16px 0 0; line-height: 1.6; text-wrap: pretty; }

  /* problem */
  .problem { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-xl); padding: 40px 44px; display: grid; grid-template-columns: 1fr 1fr; gap: 40px; align-items: center; }
  .problem .big { font-family: var(--font-display); font-weight: 700; font-size: 1.9rem; line-height: 1.2; letter-spacing: -0.02em; color: #fff; text-wrap: balance; }
  .problem .big .x { color: var(--danger-soft); }
  .problem p { color: var(--muted); font-size: 1.02rem; line-height: 1.65; margin: 0; }
  .problem p + p { margin-top: 14px; }
  .problem b { color: var(--text); font-weight: 600; }

  /* feature bento */
  .bento { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }
  .feat { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-lg); padding: 24px; transition: border-color .18s, transform .18s, background .18s; }
  .feat:hover { border-color: color-mix(in srgb, var(--cyan-500) 45%, transparent); transform: translateY(-3px); background: var(--surface-raised); }
  .feat .ic { width: 42px; height: 42px; border-radius: var(--radius-sm); background: var(--tint-primary); border: 1px solid color-mix(in srgb, var(--cyan-500) 30%, transparent); display: flex; align-items: center; justify-content: center; color: var(--cyan-300); }
  .feat .ic svg { width: 22px; height: 22px; }
  .feat h3 { font-family: var(--font-display); font-weight: 600; font-size: 1.12rem; margin: 16px 0 0; color: #fff; }
  .feat p { color: var(--muted); font-size: var(--fs-sm); line-height: 1.55; margin: 7px 0 0; }
  .feat.span2 { grid-column: span 2; display: flex; align-items: center; gap: 26px; }
  .feat.span2 .txt { flex: 1; }
  .feat.span2 .ministat { display: flex; gap: 22px; }
  .feat.span2 .ministat .n { font-family: var(--font-display); font-weight: 700; font-size: 1.8rem; color: var(--cyan-300); line-height: 1; }
  .feat.span2 .ministat .l { color: var(--faint); font-size: var(--fs-2xs); text-transform: uppercase; letter-spacing: var(--ls-label); margin-top: 5px; }

  /* pillars */
  .pillars { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; }
  .pillar { text-align: left; }
  .pillar .ic { width: 38px; height: 38px; color: var(--cyan-400); }
  .pillar .ic svg { width: 30px; height: 30px; }
  .pillar h3 { font-size: 1.02rem; font-weight: 600; color: #fff; margin: 14px 0 0; }
  .pillar p { color: var(--muted); font-size: var(--fs-sm); line-height: 1.55; margin: 6px 0 0; }
  .pillar.green .ic { color: var(--green-500); }

  /* steps */
  .steps { display: grid; grid-template-columns: repeat(3, 1fr); gap: 18px; counter-reset: s; }
  .step { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-lg); padding: 26px; position: relative; }
  .step::before { counter-increment: s; content: counter(s, decimal-leading-zero); font-family: var(--font-mono); font-size: var(--fs-xs); font-weight: 700; color: var(--cyan-400); }
  .step h3 { font-family: var(--font-display); font-weight: 600; font-size: 1.12rem; margin: 12px 0 0; color: #fff; }
  .step p { color: var(--muted); font-size: var(--fs-sm); line-height: 1.6; margin: 8px 0 0; }

  /* final CTA */
  .cta-band { position: relative; overflow: hidden; background: var(--surface); border: 1px solid color-mix(in srgb, var(--cyan-500) 30%, transparent); border-radius: var(--radius-xl); padding: 56px; text-align: center; }
  .cta-band::before { content: ""; position: absolute; inset: 0; background: radial-gradient(600px 280px at 50% -10%, color-mix(in srgb, var(--cyan-500) 16%, transparent), transparent 70%); pointer-events: none; }
  .cta-band h2 { position: relative; font-family: var(--font-display); font-weight: 700; font-size: 2.2rem; letter-spacing: -0.02em; color: #fff; margin: 0; text-wrap: balance; }
  .cta-band p { position: relative; color: var(--muted); font-size: 1.08rem; margin: 14px 0 0; }
  .cta-band .cta-row { justify-content: center; }

  /* footer */
  footer { border-top: 1px solid var(--border-soft); padding: 40px 0; margin-top: 8px; }
  .foot-inner { display: flex; justify-content: space-between; align-items: center; gap: 20px; flex-wrap: wrap; }
  .foot-inner .muted { color: var(--faint); font-size: var(--fs-xs); }
  .foot-links { display: flex; gap: 22px; }
  .foot-links a { color: var(--muted); font-size: var(--fs-sm); transition: color .15s; }
  .foot-links a:hover { color: var(--text); }

  @media (max-width: 920px) {
    .hero-grid, .problem { grid-template-columns: 1fr; }
    .bento, .pillars, .steps { grid-template-columns: 1fr; }
    .feat.span2 { grid-column: span 1; flex-direction: column; align-items: flex-start; }
    h1.hl { font-size: 2.6rem; }
  }
  @media (max-width: 640px) {
    .nav-links .lnk { display: none; }
  }
</style>
<link rel="icon" type="image/svg+xml" href="/favicon.svg" />
<link rel="icon" type="image/png" sizes="32x32" href="/favicon-32.png" />
<link rel="icon" type="image/png" sizes="16x16" href="/favicon-16.png" />
<link rel="apple-touch-icon" href="/apple-touch-icon.png" />
</head>
<body>

<!-- ============ NAV ============ -->
<nav class="nav">
  <div class="wrap nav-inner">
    <a class="brand" href="#top">
      <svg viewBox="0 0 320 290" width="34" height="31" aria-label="jobContext">
        <path d="M268.2 124.5 A80 80 0 1 0 268.2 175.5" fill="none" stroke="var(--cyan-500)" stroke-width="46" stroke-linecap="round"/>
        <circle cx="84" cy="54" r="27" fill="#fff"/>
        <path d="M84 98 L84 207 Q84 250 41 250" fill="none" stroke="#fff" stroke-width="40" stroke-linecap="round"/>
      </svg>
      <span class="wm">job<span class="c">Context</span></span>
    </a>
    <div class="nav-links">
      <a class="lnk" href="/why">Why</a>
      <a class="lnk" href="#features">Features</a>
      <a class="lnk" href="#how">How it works</a>
      <a class="lnk" href="#pillars">Why it's safe</a>
      <a class="lnk" href="https://github.com/JustLikeFrank3/jobContextMCP">GitHub</a>
      <a class="btn btn-ghost" href="/login">Sign in</a>
      <a class="btn btn-primary" href="/login">Get started</a>
    </div>
  </div>
</nav>

<span id="top"></span>

<!-- ============ HERO ============ -->
<header class="hero">
  <div class="wrap hero-grid">
    <div>
      <span class="eyebrow"><span class="dot"></span>Open-source · Model Context Protocol</span>
      <h1 class="hl">The memory layer for your <span class="c">career.</span></h1>
      <p class="lede">jobContext remembers your resumes, pipeline, contacts, posts, interviews, and your whole professional story, then feeds it to any AI assistant. Your career has context. Your AI should too.</p>
      <div class="cta-row">
        <a class="btn btn-ghost btn-lg" href="/why">Why should I use this?</a>
        <a class="btn btn-primary btn-lg" href="/login">Get started, it's free</a>
        <a class="btn btn-ghost btn-lg" href="https://github.com/JustLikeFrank3/jobContextMCP">View on GitHub</a>
      </div>
      <div class="micro">
        <span><svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 10l4 4 8-8" stroke-linecap="round" stroke-linejoin="round"/></svg>Self-hosted &amp; private</span>
        <span><svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 10l4 4 8-8" stroke-linecap="round" stroke-linejoin="round"/></svg>Works with Claude, Copilot, Cursor</span>
        <span><svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 10l4 4 8-8" stroke-linecap="round" stroke-linejoin="round"/></svg>70+ tools</span>
      </div>
    </div>

    <div class="term">
      <div class="term-bar">
        <i style="background:#ff5f57"></i><i style="background:#febc2e"></i><i style="background:#28c840"></i>
        <span class="term-title">claude · jobContext MCP</span>
      </div>
      <div class="term-body">
        <div class="u">&gt; Draft a cover letter for the CVS role.</div>
        <div class="g">&nbsp;</div>
        <div class="p">claude</div>
        <div class="g">↳ calling <span class="tool">jobContext.get_resume()</span></div>
        <div class="g">↳ calling <span class="tool">jobContext.get_job(47)</span></div>
        <div class="g">↳ calling <span class="tool">jobContext.get_stories()</span></div>
        <div class="g">&nbsp;</div>
        <div class="hl2">Done. I used your <span class="ok">master resume</span>, the</div>
        <div class="hl2">CVS assessment (<span class="ok">fitment 9/10</span>), and your</div>
        <div class="hl2">platform-migration STAR story. No</div>
        <div class="hl2">re-explaining needed.</div>
      </div>
    </div>
  </div>
</header>

<!-- ============ CLIENTS STRIP ============ -->
<div class="strip">
  <div class="wrap strip-inner">
    <span class="lbl">Plugs into your AI tools:</span>
    <span class="name">Claude</span>
    <span class="name">GitHub Copilot</span>
    <span class="name">Cursor</span>
    <span class="name">Windsurf</span>
    <span class="name">Zed</span>
    <span class="lbl">…any MCP client</span>
  </div>
</div>

<!-- ============ PROBLEM ============ -->
<section class="blk" id="why">
  <div class="wrap">
    <div class="problem">
      <div class="big">Every new AI chat starts from <span class="x">zero.</span></div>
      <div>
        <p>You paste your resume again. Re-explain the role. Re-tell the same story about that migration project. The AI is brilliant and amnesiac, and your career is scattered across tabs, docs, and DMs.</p>
        <p><b>jobContext is the memory.</b> Import once and your experience, applications, outreach, and interview notes stay in sync, ready for any assistant, any session.</p>
      </div>
    </div>
  </div>
</section>

<!-- ============ FEATURES ============ -->
<section class="blk" id="features">
  <div class="wrap">
    <div class="sec-head">
      <div class="sec-eyebrow">One source of truth</div>
      <h2>Your whole career, remembered</h2>
      <p>Not a job-board. A structured memory of everything that makes you hireable, and everything you're doing about it.</p>
    </div>
    <div class="bento">
      <div class="feat">
        <div class="ic"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M3 5h14M3 10h10M3 15h6"/></svg></div>
        <h3>Pipeline</h3>
        <p>Share-sheet intake, AI fitment scoring, resume + cover-letter generation, and an apply queue.</p>
      </div>
      <div class="feat">
        <div class="ic"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M4 4h8l4 4v11a1 1 0 01-1 1H4a1 1 0 01-1-1V5a1 1 0 011-1z"/><path d="M12 4v4h4"/></svg></div>
        <h3>Materials</h3>
        <p>Every resume, cover letter, and PDF versioned and linked to the right application.</p>
      </div>
      <div class="feat">
        <div class="ic"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><circle cx="9" cy="8" r="3.2"/><path d="M3 19c0-3.3 2.7-5.5 6-5.5"/><circle cx="17" cy="8" r="2.4"/><path d="M15.5 13.4c2.3.5 3.9 2.3 3.9 4.6"/></svg></div>
        <h3>Contacts &amp; outreach</h3>
        <p>Recruiters, referrals, and a follow-up queue so no warm intro goes cold.</p>
      </div>
      <div class="feat">
        <div class="ic"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M3 14l4-4 3 3 4-5 4 5"/><path d="M3 18h14"/></svg></div>
        <h3>LinkedIn posts</h3>
        <p>A build-in-public pipeline: draft → written → approved → posted, with engagement tracking.</p>
      </div>
      <div class="feat">
        <div class="ic"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="8" r="4"/><path d="M4 20c0-3.5 3.6-6 8-6s8 2.5 8 6"/></svg></div>
        <h3>Interviews</h3>
        <p>Schedule, prep docs, and a debrief log with verbatim quotes and what landed.</p>
      </div>
      <div class="feat">
        <div class="ic"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M3 13l3-4 3 2 3-5 3 3"/><path d="M3 17h14"/></svg></div>
        <h3>Wellbeing</h3>
        <p>A mood &amp; energy log with trend lines. The part of the search nobody tracks.</p>
      </div>
      <div class="feat span2">
        <div class="txt">
          <h3>Rejections, analyzed</h3>
          <p>Funnel-by-stage, top companies, and the patterns that turn “no” into your next yes.</p>
        </div>
        <div class="ministat">
          <div><div class="n">70+</div><div class="l">MCP tools</div></div>
          <div><div class="n">11</div><div class="l">surfaces</div></div>
        </div>
      </div>
      <div class="feat">
        <div class="ic"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M4 5h12v9H4z"/><path d="M6 8h8M6 11h5"/><path d="M16 17l3 3"/></svg></div>
        <h3>Daily digest</h3>
        <p>An on-demand morning brief: follow-ups due, stale apps, and today's priorities.</p>
      </div>
    </div>
  </div>
</section>

<!-- ============ PILLARS ============ -->
<section class="blk" id="pillars">
  <div class="wrap">
    <div class="sec-head">
      <div class="sec-eyebrow">Built for what matters</div>
      <h2>Private by design, yours to own</h2>
    </div>
    <div class="pillars">
      <div class="pillar">
        <div class="ic"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l7 3v5c0 4.4-3 7.6-7 9-4-1.4-7-4.6-7-9V6l7-3z"/><path d="M9 12l2 2 4-4"/></svg></div>
        <h3>Private &amp; secure</h3>
        <p>Self-hosted with HTTP-only sessions. Your data never leaves your server.</p>
      </div>
      <div class="pillar green">
        <div class="ic"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><ellipse cx="12" cy="6" rx="7" ry="3"/><path d="M5 6v6c0 1.7 3.1 3 7 3s7-1.3 7-3V6"/><path d="M5 12v6c0 1.7 3.1 3 7 3s7-1.3 7-3v-6"/></svg></div>
        <h3>You own your data</h3>
        <p>Plain files and an open schema. Export anytime. No lock-in, ever.</p>
      </div>
      <div class="pillar">
        <div class="ic"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M7 18a4 4 0 010-8 5 5 0 019.6-1.3A3.5 3.5 0 0117 18H7z"/></svg></div>
        <h3>Works everywhere</h3>
        <p>One MCP server, every client: Claude, Copilot, Cursor, Windsurf, Zed.</p>
      </div>
      <div class="pillar">
        <div class="ic"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M10 4a1.5 1.5 0 013 0c0 .4-.2.8-.4 1.1.3.2.7.3 1.1.3h2.3v2.3c0 .4.1.8.3 1.1.3-.2.7-.4 1.1-.4a1.5 1.5 0 010 3c-.4 0-.8-.2-1.1-.4-.2.3-.3.7-.3 1.1V15h-2.3c-.4 0-.8.1-1.1.3.2.3.4.7.4 1.1a1.5 1.5 0 01-3 0c0-.4.2-.8.4-1.1-.3-.2-.7-.3-1.1-.3H5.6v-2.3c0-.4-.1-.8-.3-1.1-.3.2-.7.4-1.1.4a1.5 1.5 0 010-3c.4 0 .8.2 1.1.4.2-.3.3-.7.3-1.1V5.7h2.3c.4 0 .8-.1 1.1-.3-.2-.3-.4-.7-.4-1.1z"/></svg></div>
        <h3>Extensible</h3>
        <p>70+ open tools and a clean API. Bend it to your own workflow.</p>
      </div>
    </div>
  </div>
</section>

<!-- ============ HOW IT WORKS ============ -->
<section class="blk" id="how">
  <div class="wrap">
    <div class="sec-head">
      <div class="sec-eyebrow">Up and running in minutes</div>
      <h2>Import once. Stay in sync.</h2>
    </div>
    <div class="steps">
      <div class="step">
        <h3>Connect your MCP client</h3>
        <p>Point Claude, Copilot, or Cursor at your jobContext server. One config line.</p>
      </div>
      <div class="step">
        <h3>Import your career</h3>
        <p>Drop in your resume and history. jobContext structures it into a queryable memory.</p>
      </div>
      <div class="step">
        <h3>Let your AI remember</h3>
        <p>Every session now starts with full context: applications, stories, contacts, and all.</p>
      </div>
    </div>
  </div>
</section>

<!-- ============ FINAL CTA ============ -->
<section class="blk" style="padding-top:24px;">
  <div class="wrap">
    <div class="cta-band">
      <h2>Give your AI a memory.</h2>
      <p>Open-source, self-hosted, and free. Your career has context. Your AI should too.</p>
      <div class="cta-row">
        <a class="btn btn-primary btn-lg" href="/login">Get started</a>
        <a class="btn btn-ghost btn-lg" href="https://github.com/JustLikeFrank3/jobContextMCP">Star on GitHub</a>
      </div>
    </div>
  </div>
</section>

<!-- ============ FOOTER ============ -->
<footer>
  <div class="wrap foot-inner">
    <a class="brand" href="#top">
      <svg viewBox="0 0 320 290" width="26" height="24" aria-label="jobContext">
        <path d="M268.2 124.5 A80 80 0 1 0 268.2 175.5" fill="none" stroke="var(--cyan-500)" stroke-width="46" stroke-linecap="round"/>
        <circle cx="84" cy="54" r="27" fill="#fff"/>
        <path d="M84 98 L84 207 Q84 250 41 250" fill="none" stroke="#fff" stroke-width="40" stroke-linecap="round"/>
      </svg>
      <span class="wm" style="font-size:1.1rem">job<span class="c">Context</span></span>
    </a>
    <div class="foot-links">
      <a href="#features">Features</a>
      <a href="#how">How it works</a>
      <a href="https://github.com/JustLikeFrank3/jobContextMCP">GitHub</a>
      <a href="/login">Sign in</a>
    </div>
    <div class="muted">© 2026 jobContext · The memory layer for your career.</div>
  </div>
</footer>

</body>
</html>
'''


def landing_html() -> str:
    return LANDING_HTML
