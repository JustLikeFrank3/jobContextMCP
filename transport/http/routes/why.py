"""Public Why-use-it page for jobContext (suggested route: /why).
Self-contained: design tokens + Google Fonts inlined, mirrors landing.py.
Serve it the same way landing.py is served, e.g. return WHY_HTML from a /why handler.
"""
from __future__ import annotations

WHY_HTML: str = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>jobContext &mdash; Why use it</title>
<style id="ds-tokens">
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500;600;700&display=swap');
/* ============================================================
   jobContext — Color tokens
   Redesign palette. Anchored on the brand sheet: deep navy ink,
   vivid cyan primary (#00B5C8), confirmation green (#22C55E,
   the "$" in the mark), warm slate neutrals, off-white text.
   The live dashboard's muted teal (#00B5C8) is retired in favour
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
  --cyan-500: #00B5C8;  /* PRIMARY — actions, links, focus     */
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
  --info:   #00B5C8;

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
    .nav-links .lnk { display: none; }
  }
</style>
<link rel="icon" type="image/svg+xml" href="/favicon.svg" />
<link rel="icon" type="image/png" sizes="32x32" href="/favicon-32.png" />
<link rel="icon" type="image/png" sizes="16x16" href="/favicon-16.png" />
<link rel="apple-touch-icon" href="/apple-touch-icon.png" />

<style>
  /* ---- additions for the Why page (built on existing tokens) ---- */
  .pagehead { padding: 76px 0 8px; position: relative; overflow: hidden; }
  .pagehead::before { content:""; position:absolute; inset:0;
    background: radial-gradient(620px 360px at 75% 0%, color-mix(in srgb, var(--cyan-500) 12%, transparent), transparent 70%); pointer-events:none; }
  .pagehead .inner { position: relative; max-width: 760px; }
  .pagehead h1 { font-family: var(--font-display); font-weight: 700; font-size: 3.1rem; line-height: 1.05; letter-spacing: -0.03em; color:#fff; margin: 20px 0 0; text-wrap: balance; }
  .pagehead h1 .c { color: var(--cyan-400); }
  .pagehead .lede { color: var(--muted); font-size: 1.2rem; line-height: 1.6; margin: 20px 0 0; max-width: 34em; text-wrap: pretty; }

  /* before / after */
  .ba { display:grid; grid-template-columns: 1fr 1fr; gap:16px; }
  .ba .col { border-radius: var(--radius-lg); padding: 26px 26px 28px; border:1px solid var(--border); }
  .ba .col.before { background: var(--surface); }
  .ba .col.after  { background: var(--surface); border-color: color-mix(in srgb, var(--cyan-500) 35%, transparent); }
  .ba .tag { display:inline-flex; align-items:center; gap:8px; font-size: var(--fs-2xs); font-weight:700; text-transform:uppercase; letter-spacing: var(--ls-eyebrow); padding:5px 11px; border-radius: var(--radius-pill); }
  .ba .before .tag { color: var(--danger-soft); background: var(--tint-danger); }
  .ba .after .tag  { color: var(--cyan-300); background: var(--tint-primary); }
  .ba ul { list-style:none; margin: 18px 0 0; padding:0; }
  .ba li { color: var(--muted); font-size: var(--fs-body); line-height: 1.55; padding-left: 26px; position: relative; margin-top: 12px; }
  .ba li::before { position:absolute; left:0; top:1px; font-family: var(--font-mono); font-weight:700; }
  .ba .before li::before { content:"\00d7"; color: var(--danger-soft); }
  .ba .after  li::before { content:"\2713"; color: var(--green-500); }
  .ba .after li b { color: var(--text); font-weight: 600; }

  /* best practices list */
  .bp { display:grid; grid-template-columns: 1fr 1fr; gap:16px; }
  .bp .item { background: var(--surface); border:1px solid var(--border); border-radius: var(--radius-lg); padding: 22px 24px; transition: border-color .18s, background .18s; }
  .bp .item:hover { border-color: color-mix(in srgb, var(--cyan-500) 40%, transparent); background: var(--surface-raised); }
  .bp .k { font-family: var(--font-mono); font-size: var(--fs-2xs); font-weight:700; color: var(--cyan-400); text-transform: uppercase; letter-spacing: var(--ls-label); }
  .bp h3 { font-family: var(--font-display); font-weight:600; font-size: 1.08rem; color:#fff; margin: 10px 0 0; }
  .bp p { color: var(--muted); font-size: var(--fs-sm); line-height: 1.6; margin: 8px 0 0; }

  /* who it's for */
  .who { background: var(--surface); border:1px solid var(--border); border-radius: var(--radius-xl); padding: 36px 40px; display:grid; grid-template-columns: 1fr 1fr; gap: 36px; }
  .who h3 { font-family: var(--font-display); font-weight:600; font-size: 1.18rem; margin:0 0 6px; }
  .who .yes h3 { color: var(--green-300); }
  .who .no h3  { color: var(--faint); }
  .who ul { list-style:none; margin: 14px 0 0; padding:0; }
  .who li { color: var(--muted); font-size: var(--fs-body); line-height:1.5; padding-left: 24px; position:relative; margin-top: 11px; }
  .who .yes li::before { content:"\2713"; position:absolute; left:0; color: var(--green-500); font-family: var(--font-mono); font-weight:700; }
  .who .no li::before  { content:"\2013"; position:absolute; left:0; color: var(--faint); font-family: var(--font-mono); font-weight:700; }

  @media (max-width: 920px) {
    .ba, .bp, .who { grid-template-columns: 1fr; }
    .pagehead h1 { font-size: 2.4rem; }
  }
</style>
<link rel="icon" type="image/svg+xml" href="/favicon.svg" />
</head>

<body>

<nav class="nav">
  <div class="wrap nav-inner">
    <a class="brand" href="/">
      <svg viewBox="0 0 320 320" width="34" height="34" aria-label="jobContext">
        <circle cx="160" cy="160" r="153" fill="#0A0F1C"/>
        <circle cx="160" cy="160" r="153" fill="none" stroke="var(--cyan-500)" stroke-width="10"/>
        <g transform="translate(-12 0)">
          <path d="M234 118 A56 56 0 1 0 234 202" fill="none" stroke="var(--cyan-500)" stroke-width="32" stroke-linecap="round"/>
          <circle cx="100" cy="112" r="19" fill="#fff"/>
          <path d="M100 142 L100 205 Q100 230 74 230" fill="none" stroke="#fff" stroke-width="30" stroke-linecap="round"/>
        </g>
      </svg>
      <span class="wm">job<span class="c">Context</span></span>
    </a>
    <div class="nav-links">
      <a class="lnk" href="#value">Why</a>
      <a class="lnk" href="#how">How it works</a>
      <a class="lnk" href="#best">Best practices</a>
      <a class="lnk" href="#safe">Why it's safe</a>
      <a class="btn btn-ghost" href="/login">Sign in</a>
      <a class="btn btn-primary" href="/login">Get started</a>
    </div>
  </div>
</nav>

<span id="top"></span>

<!-- PAGE HEAD -->
<header class="pagehead">
  <div class="wrap inner">
    <span class="eyebrow"><span class="dot"></span>Why jobContext</span>
    <h1>Stop re-explaining yourself to AI <span class="c">every morning.</span></h1>
    <p class="lede">Your job search is scattered across thirty browser tabs, a spreadsheet, your inbox, and your memory. jobContext gives your AI assistant a memory of all of it, so every conversation picks up where you left off instead of starting from zero.</p>
    <div class="cta-row">
      <a class="btn btn-primary btn-lg" href="/login">Get started - it's free</a>
      <a class="btn btn-ghost btn-lg" href="#how">See how it works</a>
    </div>
  </div>
</header>

<!-- THE PROBLEM / VALUE -->
<section class="blk" id="value">
  <div class="wrap">
    <div class="sec-head">
      <div class="sec-eyebrow">The difference</div>
      <h2>What changes the moment it is connected</h2>
      <p>An AI assistant without your context is a brilliant stranger. Connected to jobContext, it is a teammate who has been with you the whole search.</p>
    </div>
    <div class="ba">
      <div class="col before">
        <span class="tag">Without it</span>
        <ul>
          <li>You paste your resume into every new chat</li>
          <li>You re-explain who you talked to and what you said</li>
          <li>You remind it of your rate, your targets, your story</li>
          <li>Advice is generic because it knows nothing about you</li>
          <li>Your history lives in your head and a messy spreadsheet</li>
        </ul>
      </div>
      <div class="col after">
        <span class="tag">With it</span>
        <ul>
          <li>It already knows your <b>background and pipeline</b> on hello</li>
          <li>It knows every <b>contact and conversation</b> in your search</li>
          <li>Drafts come out in <b>your voice</b>, grounded in your real wins</li>
          <li>It tells you <b>what to do next</b>, not just answers questions</li>
          <li>The record <b>builds itself</b> as you talk</li>
        </ul>
      </div>
    </div>
  </div>
</section>

<!-- WHAT IT DOES: MEMORY -->
<section class="blk" style="padding-top:0;">
  <div class="wrap">
    <div class="sec-head">
      <div class="sec-eyebrow">Memory &amp; continuity</div>
      <h2>It remembers, so you don't have to</h2>
    </div>
    <div class="bento"><div class="feat"><div class="ic"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="4" y="4" width="16" height="16" rx="2"/><path d="M9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3"/></svg></div><h3>It already knows you</h3><p>Resume, work history, metrics, and your live pipeline are loaded the moment you say hello. No more pasting your background into a fresh chat every single time.</p></div><div class="feat"><div class="ic"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="9" cy="8" r="3.2"/><path d="M3.5 20a5.5 5.5 0 0 1 11 0"/><path d="M16 5.2a3 3 0 0 1 0 5.6M17.5 20a5.5 5.5 0 0 0-3-4.9"/></svg></div><h3>Every contact, remembered</h3><p>Recruiters, referrals, hiring managers, what you last said, when you last reached out, what is still pending. The next message gets written with full context, not guesswork.</p></div><div class="feat"><div class="ic"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M4 5h16M4 10h10M4 15h16M4 19h7"/></svg></div><h3>Sounds like you</h3><p>It learns your writing voice from your real messages, so drafts come out in your tone instead of generic AI filler.</p></div></div>
  </div>
</section>

<!-- WHAT IT DOES: ACTION -->
<section class="blk" style="padding-top:0;">
  <div class="wrap">
    <div class="sec-head">
      <div class="sec-eyebrow">Direction &amp; action</div>
      <h2>It moves the search forward</h2>
    </div>
    <div class="bento"><div class="feat"><div class="ic"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="9"/><path d="M15.5 8.5l-2 5-5 2 2-5z"/></svg></div><h3>Tells you what is next</h3><p>Overdue follow-ups, who is waiting on you, threads going stale, today's priorities. A chaotic search becomes a managed pipeline.</p></div><div class="feat"><div class="ic"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="4.5"/><circle cx="12" cy="12" r="0.6" fill="currentColor"/></svg></div><h3>Honest fit checks</h3><p>Paste a job description and get a real read against your background: where you match, where the gaps are, and whether it is worth your time.</p></div><div class="feat"><div class="ic"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M6 2.5h8l4 4V21a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V3.5a1 1 0 0 1 1-1z"/><path d="M14 2.5V7h4M8 13h8M8 17h6"/></svg></div><h3>Tailored applications, fast</h3><p>Resumes and cover letters built per role in minutes, anchored to your master resume and the metrics you actually earned.</p></div></div>
  </div>
</section>

<!-- HOW IT WORKS -->
<section class="blk" id="how" style="padding-top:0;">
  <div class="wrap">
    <div class="sec-head">
      <div class="sec-eyebrow">How it works</div>
      <h2>Connected in about a minute</h2>
      <p>The hosted version needs no setup files and no infrastructure. Add the connector, sign in, and start talking.</p>
    </div>
    <div class="steps">
      <div class="step"><h3>Add the connector</h3><p>In Claude, Copilot, Cursor, or Windsurf, add jobContext as a connector. One click. No config files to edit, nothing to install.</p></div>
      <div class="step"><h3>Sign in with Microsoft</h3><p>Authenticate with your Microsoft account. Your private, isolated workspace is created for you in the cloud.</p></div>
      <div class="step"><h3>Just start talking</h3><p>Ask it to log a contact, assess a job, draft a cover letter, or plan your day. It does the rest, and remembers all of it next time.</p></div>
    </div>
  </div>
</section>

<!-- BEST PRACTICES -->
<section class="blk" id="best" style="padding-top:0;">
  <div class="wrap">
    <div class="sec-head">
      <div class="sec-eyebrow">Best practices</div>
      <h2>How to get the most out of it</h2>
      <p>The people who get the most from jobContext treat it like a teammate they keep in the loop, not a tool they open once.</p>
    </div>
    <div class="bp"><div class="item"><div class="k">Practice 01</div><h3>Just talk, it logs itself</h3><p>Tell it what happened in plain language. "Had a call with Sam, sending my resume Friday." It records the contact, the message, and the follow-up automatically. The conversation is the record.</p></div><div class="item"><div class="k">Practice 02</div><h3>Drop in job descriptions</h3><p>Paste a posting and ask for a fit assessment before you spend an evening applying. Let it tell you the angles to lead with and the gaps to address.</p></div><div class="item"><div class="k">Practice 03</div><h3>Start your day with the digest</h3><p>Ask for your daily briefing. It surfaces what is overdue, who owes you a reply, and the three things actually worth doing today.</p></div><div class="item"><div class="k">Practice 04</div><h3>Debrief every interview</h3><p>Right after a call, walk through how it went. It captures what landed, what did not, and what the team really cared about, then feeds that into prep for the next round.</p></div><div class="item"><div class="k">Practice 05</div><h3>Keep people current</h3><p>Whenever someone new enters your search, mention them. A search lives or dies on relationships, and the ones it remembers are the ones you can act on.</p></div><div class="item"><div class="k">Practice 06</div><h3>Use it from your phone</h3><p>See a posting on the move? Share it straight into your pipeline with the mobile share sheet, then assess it later from your desk.</p></div></div>
  </div>
</section>

<!-- WHO IT'S FOR -->
<section class="blk" style="padding-top:0;">
  <div class="wrap">
    <div class="sec-head">
      <div class="sec-eyebrow">Honest fit</div>
      <h2>Who this is really for</h2>
      <p>It pays off most when your search has a lot of moving parts. If you are casually browsing one role a month, the memory layer is more than you need.</p>
    </div>
    <div class="who">
      <div class="yes">
        <h3>You'll feel it if</h3>
        <ul>
          <li>You have several roles in flight at once</li>
          <li>You are juggling recruiters, referrals, and follow-ups</li>
          <li>You are interviewing and need to prep and debrief fast</li>
          <li>You are tired of re-explaining yourself to AI every time</li>
          <li>You want your search managed, not just remembered</li>
        </ul>
      </div>
      <div class="no">
        <h3>Probably overkill if</h3>
        <ul>
          <li>You are applying to one job a month</li>
          <li>You are not using an AI assistant in your search</li>
          <li>You just want a resume formatter and nothing more</li>
        </ul>
      </div>
    </div>
  </div>
</section>

<!-- WHY IT'S SAFE -->
<section class="blk" id="safe" style="padding-top:0;">
  <div class="wrap">
    <div class="sec-head">
      <div class="sec-eyebrow">Why it's safe</div>
      <h2>Built to be trusted with your career</h2>
      <p>You are handing it the story of your professional life. It is built to earn that.</p>
    </div>
    <div class="pillars"><div class="pillar green"><div class="ic"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 3l7 3v5c0 4.5-3 8-7 10-4-2-7-5.5-7-10V6z"/><path d="M9 12l2 2 4-4"/></svg></div><h3>It will not make things up</h3><p>A no-fabrication guardrail lives in the system, not a prompt. It cannot invent metrics to flatter you. Everything traces back to your real record.</p></div><div class="pillar"><div class="ic"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/></svg></div><h3>Your data is isolated</h3><p>Multi-tenant with per-user separation. Your search is yours. Nobody else can see it, and your data never leaks into anyone else's.</p></div><div class="pillar"><div class="ic"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M9 19c-4 1.3-4-2.2-6-2.7M15 21v-3.4a3 3 0 0 0-.8-2.3c2.8-.3 5.6-1.4 5.6-6a4.6 4.6 0 0 0-1.3-3.2 4.3 4.3 0 0 0-.1-3.2s-1-.3-3.4 1.3a11.6 11.6 0 0 0-6 0C6.6 1.6 5.6 1.9 5.6 1.9a4.3 4.3 0 0 0-.1 3.2A4.6 4.6 0 0 0 4.2 8.3c0 4.6 2.8 5.7 5.6 6a3 3 0 0 0-.8 2.3V21"/></svg></div><h3>Open and inspectable</h3><p>The whole thing is open source. You can read exactly how it works, run your own copy, or just trust the hosted version. No black box.</p></div><div class="pillar green"><div class="ic"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M4 20V4M4 20h16M8 16v-4M12 16V8M16 16v-7"/></svg></div><h3>Built and battle-tested</h3><p>Running in production on Azure with hundreds of automated tests behind it. This is a real system, not a weekend demo.</p></div></div>
  </div>
</section>

<!-- FINAL CTA -->
<section class="blk" style="padding-top:0;">
  <div class="wrap">
    <div class="cta-band">
      <h2>Give your AI a memory of your career.</h2>
      <p>Free to start. Connect in a minute. Your search, finally in one place.</p>
      <div class="cta-row">
        <a class="btn btn-primary btn-lg" href="/login">Get started - it's free</a>
        <a class="btn btn-ghost btn-lg" href="https://github.com/JustLikeFrank3/jobContextMCP">View on GitHub</a>
      </div>
    </div>
  </div>
</section>

<!-- FOOTER -->
<footer>
  <div class="wrap foot-inner">
    <span class="muted">jobContext - the memory layer for your career.</span>
    <div class="foot-links">
      <a href="/">Home</a>
      <a href="#how">How it works</a>
      <a href="https://github.com/JustLikeFrank3/jobContextMCP">GitHub</a>
      <a href="/login">Sign in</a>
    </div>
  </div>
</footer>
</body>
</html>
'''


def why_html() -> str:
    return WHY_HTML
