"""Public Privacy Policy page (served at /privacy). Self-contained."""
from __future__ import annotations

PRIVACY_HTML: str = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Privacy Policy &mdash; jobContext</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500;600;700&display=swap');
:root {
  --ink-950:#070B14;--ink-900:#0A0F1C;--ink-850:#0B1220;--ink-800:#0F172A;
  --ink-700:#111A2B;--ink-600:#16213A;--ink-500:#1B2A44;--ink-450:#22324E;
  --line:#23324D;--line-soft:#1A2740;--line-strong:#2E4366;
  --cyan-500:#00B5C8;--cyan-400:#22C7E0;--cyan-300:#6FE0EE;
  --green-500:#22C55E;
  --text:#F2F6FC;--text-strong:#FFFFFF;--text-soft:#D7E3F8;
  --muted:#9AA8BF;--faint:#6B7A93;
  --font-body:'Space Grotesk',system-ui,sans-serif;
  --font-mono:'JetBrains Mono',monospace;
}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0;}
html{font-size:16px;scroll-behavior:smooth;}
body{background:linear-gradient(160deg,var(--ink-900) 0%,var(--ink-850) 100%);color:var(--text);font-family:var(--font-body);min-height:100vh;line-height:1.7;}
a{color:var(--cyan-500);text-decoration:none;}
a:hover{color:var(--cyan-400);text-decoration:underline;}
nav{position:sticky;top:0;z-index:100;background:rgba(10,15,28,.92);backdrop-filter:blur(12px);border-bottom:1px solid var(--line);padding:0 1.5rem;}
.nav-inner{max-width:780px;margin:0 auto;display:flex;align-items:center;justify-content:space-between;height:54px;}
.brand{display:flex;align-items:center;gap:.5rem;font-weight:600;color:var(--text-strong);}
.brand .c{color:var(--cyan-500);}
.nav-links{display:flex;gap:1.5rem;font-size:.875rem;}
.nav-links a{color:var(--muted);}
.nav-links a:hover{color:var(--text);text-decoration:none;}
.wrap{max-width:780px;margin:0 auto;padding:3rem 1.5rem 5rem;}
.page-eyebrow{font-size:.75rem;font-weight:600;letter-spacing:.12em;text-transform:uppercase;color:var(--cyan-500);margin-bottom:.75rem;}
h1{font-size:2rem;font-weight:700;color:var(--text-strong);line-height:1.15;margin-bottom:.5rem;}
.meta{color:var(--muted);font-size:.9rem;margin-bottom:2.5rem;padding-bottom:1.5rem;border-bottom:1px solid var(--line);}
/* Short version callout */
.summary-box{background:var(--ink-700);border:1px solid var(--line-strong);border-left:3px solid var(--cyan-500);border-radius:8px;padding:1.25rem 1.5rem;margin-bottom:2.5rem;}
.summary-box h3{font-size:.8rem;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:var(--cyan-500);margin-bottom:.75rem;}
.summary-box ul{padding-left:1.25rem;color:var(--text-soft);font-size:.9rem;}
.summary-box ul li{margin-bottom:.4rem;}
/* Body content */
h2{font-size:1.1rem;font-weight:700;color:var(--text-strong);margin:2rem 0 .6rem;padding-bottom:.4rem;border-bottom:1px solid var(--line-soft);}
p{color:var(--muted);font-size:.95rem;margin-bottom:.75rem;}
table{width:100%;border-collapse:collapse;margin:1rem 0;font-size:.875rem;}
th{text-align:left;padding:.5rem .75rem;color:var(--text-soft);font-weight:600;border-bottom:1px solid var(--line);}
td{padding:.5rem .75rem;color:var(--muted);border-bottom:1px solid var(--line-soft);}
strong{color:var(--text-soft);font-weight:600;}
/* Footer */
footer{border-top:1px solid var(--line);padding:1.5rem;}
.foot-inner{max-width:780px;margin:0 auto;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:.75rem;}
.foot-links{display:flex;gap:1.25rem;flex-wrap:wrap;}
.foot-links a{color:var(--muted);font-size:.875rem;}
.foot-links a:hover{color:var(--text);text-decoration:none;}
.muted{color:var(--muted);font-size:.875rem;}
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
      <a href="/terms">Terms</a>
      <a href="/login">Sign in</a>
    </div>
  </div>
</nav>

<div class="wrap">
  <div class="page-eyebrow">Legal</div>
  <h1>Privacy Policy</h1>
  <div class="meta">
    <strong>Effective date:</strong> June 26, 2026 &nbsp;&middot;&nbsp;
    <strong>Operator:</strong> Frank MacBride &nbsp;&middot;&nbsp;
    <a href="mailto:admin@jobcontext.ai">admin@jobcontext.ai</a>
  </div>

  <div class="summary-box">
    <h3>The short version</h3>
    <ul>
      <li>We collect what you put into jobContext (your career stuff) plus basic account info from your Microsoft sign-in. That is it.</li>
      <li>We never sell your data, never use it for ads, and never use it to train our own models.</li>
      <li>To build resumes, cover letters, and prep, we send the relevant parts to AI providers (Anthropic and OpenAI) that do not keep your data or train on it.</li>
      <li>The wellbeing check-in is opt-in. If you never log one, there is no mood data at all. You can delete any or all of it whenever you want.</li>
      <li>Anything you record about other people (recruiters, referrals) stays your private address book. We do not market to them and do not sell it.</li>
      <li>You can see, export, and delete everything, including your entire account, at any time.</li>
    </ul>
  </div>

  <h2>1. Who this policy covers</h2>
  <p>This policy covers people who sign in to and use jobContext (our &ldquo;users&rdquo;). It also explains how we handle information a user records about other people, such as recruiters or referral contacts. If you are one of those third parties and have a question about your information, contact us at <a href="mailto:admin@jobcontext.ai">admin@jobcontext.ai</a>.</p>

  <h2>2. Information we collect</h2>
  <p>We collect only what we need to run the Service.</p>
  <p><strong>Account and identity information.</strong> You sign in with Microsoft (Microsoft Entra ID). We receive your name, email address, Microsoft Entra object ID, and tenant ID. We do not receive your Microsoft password.</p>
  <p><strong>Career information you provide.</strong> This is the core of the Service: resume content, work history, skills, accomplishments, personal stories, job descriptions, applications, interview notes, outreach messages, and similar materials.</p>
  <p><strong>Contacts you record about other people.</strong> You can record information about recruiters, hiring managers, or referral contacts &mdash; their name, employer, role, and your notes. This functions as your professional address book.</p>
  <p><strong>Optional wellbeing check-ins.</strong> Entirely opt-in. If you never record a check-in, no mood data is collected. When you do, we store the mood label, energy rating, and any note you write solely to show you your own history and trends.</p>
  <p><strong>Usage and technical information.</strong> Limited technical data such as feature usage, timestamps, error logs, and basic request metadata to keep the Service running.</p>
  <p>We do not collect payment information during the beta.</p>

  <h2>3. How we use information</h2>
  <p>We use information to provide and secure your account, generate the outputs you ask for, maintain and improve the Service, communicate with you about the beta, and comply with legal obligations. We do not sell your personal information, use it for advertising, or use it to train our own models.</p>

  <h2>4. Contacts you record about other people</h2>
  <p>Information you record about third parties is processed only to provide the Service to you. We do not market to these individuals or sell their information. You are responsible for ensuring you have a lawful basis to record information about other people and for using it responsibly.</p>

  <h2>5. Sensitive information (wellbeing check-ins)</h2>
  <p>The optional wellbeing check-in feature involves information about your mental or emotional state, treated as sensitive personal information. It is entirely opt-in, used only to display your own history back to you, never sold, never used for advertising, never used to train any model, and you can delete any check-in at any time.</p>

  <h2>6. How your information is processed and who we share it with</h2>
  <p><strong>AI processing.</strong> We send relevant portions of your data to Anthropic and OpenAI through their commercial APIs. Under those terms, these providers process data only to return a result for your request, do not retain it, and do not train on it.</p>
  <p><strong>Hosting and authentication.</strong> The Service runs on Microsoft Azure.</p>
  <table>
    <tr><th>Sub-processor</th><th>Purpose</th><th>Location</th></tr>
    <tr><td>Microsoft Azure</td><td>Hosting, infrastructure, authentication</td><td>United States</td></tr>
    <tr><td>Anthropic</td><td>AI text generation (no training, no retention)</td><td>United States</td></tr>
    <tr><td>OpenAI</td><td>AI text generation (no training, no retention)</td><td>United States</td></tr>
  </table>

  <h2>7. Where your data is stored</h2>
  <p>Your data is stored in Microsoft Azure data centers in the United States. Each account&rsquo;s data is held in a separate, isolated per-user store.</p>

  <h2>8. How long we keep your data</h2>
  <p>We keep your data for as long as your account is active. You can delete individual items or your entire account at any time. When you delete your account, we remove your data from active systems. Residual copies in backups are purged on our standard cycle.</p>

  <h2>9. Your choices and rights</h2>
  <p>You can access, correct, export, and delete your information at any time through the Service. Depending on where you live, you may have additional rights under laws such as the California Consumer Privacy Act. To exercise any right not available directly in the Service, contact us at <a href="mailto:admin@jobcontext.ai">admin@jobcontext.ai</a>.</p>

  <h2>10. Security</h2>
  <p>We protect your data with Microsoft Entra ID authentication and per-user data isolation. No system is perfectly secure, but we work to safeguard your information. If we become aware of a breach affecting your personal information, we will notify you as required by law.</p>

  <h2>11. Children</h2>
  <p>The Service is not directed to anyone under 18. We do not knowingly collect personal information from anyone under 18. If you believe a minor has provided us information, contact us and we will delete it.</p>

  <h2>12. Changes to this policy</h2>
  <p>We may update this policy as the Service evolves. If we make material changes, we will notify you through the Service or by email and update the effective date. Your continued use after an update means you accept the revised policy.</p>

  <h2>13. Contact</h2>
  <p><a href="mailto:admin@jobcontext.ai">admin@jobcontext.ai</a><br>Frank MacBride</p>
</div>

<footer>
  <div class="foot-inner">
    <span class="muted">&copy; 2026 jobContext &mdash; Frank MacBride</span>
    <div class="foot-links">
      <a href="/">Home</a>
      <a href="/why">Why jobContext</a>
      <a href="/setup">Getting started</a>
      <a href="/privacy">Privacy</a>
      <a href="/terms">Terms</a>
      <a href="/login">Sign in</a>
    </div>
  </div>
</footer>
</body>
</html>
'''


def privacy_html() -> str:
    return PRIVACY_HTML
