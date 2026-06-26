"""Public Terms of Service page (served at /terms). Self-contained."""
from __future__ import annotations

TERMS_HTML: str = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Terms of Service &mdash; jobContext</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500;600;700&display=swap');
:root {
  --ink-950:#070B14;--ink-900:#0A0F1C;--ink-850:#0B1220;--ink-800:#0F172A;
  --ink-700:#111A2B;--ink-600:#16213A;--ink-500:#1B2A44;--ink-450:#22324E;
  --line:#23324D;--line-soft:#1A2740;--line-strong:#2E4366;
  --cyan-500:#06B6D4;--cyan-400:#22C7E0;--cyan-300:#6FE0EE;
  --green-500:#22C55E;
  --text:#F2F6FC;--text-strong:#FFFFFF;--text-soft:#D7E3F8;
  --muted:#9AA8BF;--faint:#6B7A93;
  --font-body:'Space Grotesk',system-ui,sans-serif;
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
.summary-box{background:var(--ink-700);border:1px solid var(--line-strong);border-left:3px solid var(--cyan-500);border-radius:8px;padding:1.25rem 1.5rem;margin-bottom:2.5rem;}
.summary-box h3{font-size:.8rem;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:var(--cyan-500);margin-bottom:.75rem;}
.summary-box ul{padding-left:1.25rem;color:var(--text-soft);font-size:.9rem;}
.summary-box ul li{margin-bottom:.4rem;}
h2{font-size:1.1rem;font-weight:700;color:var(--text-strong);margin:2rem 0 .6rem;padding-bottom:.4rem;border-bottom:1px solid var(--line-soft);}
p{color:var(--muted);font-size:.95rem;margin-bottom:.75rem;}
ul.body-list{padding-left:1.5rem;color:var(--muted);font-size:.95rem;margin-bottom:.75rem;}
ul.body-list li{margin-bottom:.35rem;}
strong{color:var(--text-soft);font-weight:600;}
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
      <a href="/privacy">Privacy</a>
      <a href="/login">Sign in</a>
    </div>
  </div>
</nav>

<div class="wrap">
  <div class="page-eyebrow">Legal</div>
  <h1>Terms of Service</h1>
  <div class="meta">
    <strong>Effective date:</strong> [DATE] &nbsp;&middot;&nbsp;
    <strong>Operator:</strong> Frank MacBride &nbsp;&middot;&nbsp;
    <a href="mailto:support@jobcontext.ai">support@jobcontext.ai</a>
  </div>

  <div class="summary-box">
    <h3>The short version</h3>
    <ul>
      <li>jobContext is an early beta. It will have rough edges, it can change or go down, so keep your own copies of anything important.</li>
      <li>You own everything you put in. We only use it to run the service for you.</li>
      <li>The AI can be wrong. Always read and edit anything it generates before you send it to a real person.</li>
      <li>This is a tool, not advice. It is not legal, financial, or career counsel, and the wellbeing check-in is a personal tracker, not a mental-health service.</li>
      <li>Do not use it to reach anyone else&rsquo;s data, and do not record information about people you have no right to hold.</li>
      <li>You can leave and delete your account anytime.</li>
    </ul>
  </div>

  <h2>1. Eligibility</h2>
  <p>You must be at least 18 years old and able to form a binding contract to use the Service. The Service is currently offered as an invite-only beta to users in the United States. You may use it only if you have received an invitation and access has not been revoked.</p>

  <h2>2. The Service</h2>
  <p>jobContext is a career-memory service that stores career-related information you provide and uses it, together with third-party AI providers, to help generate materials such as tailored resumes, cover letters, interview preparation, and message drafts. The Service does not guarantee any job, interview, offer, or other outcome.</p>

  <h2>3. Your account and Microsoft sign-in</h2>
  <p>You access the Service by signing in with Microsoft (Microsoft Entra ID). You are responsible for maintaining the security of your Microsoft account and for all activity under your jobContext account. Notify us promptly of any unauthorized use.</p>

  <h2>4. Your content and ownership</h2>
  <p>You retain ownership of the information and materials you put into the Service (&ldquo;Your Content&rdquo;). You grant us a limited license to host, store, process, and transmit Your Content solely to operate and provide the Service to you. We do not claim ownership of Your Content and we do not use it to train our own models.</p>

  <h2>5. Information about other people</h2>
  <p>If you record information about other individuals, you represent that you have a lawful and appropriate basis to do so and that you will use the Service in compliance with applicable privacy laws. You agree not to use the Service to record information you are not permitted to hold or to harass, surveil, or harm any person.</p>

  <h2>6. AI-generated output</h2>
  <p>AI output can be inaccurate, incomplete, or unsuitable for a given purpose. You are responsible for reviewing, editing, and verifying any output before you rely on it or send it to anyone. We are not responsible for decisions you make based on AI-generated output.</p>

  <h2>7. No professional advice</h2>
  <p>The Service does not provide legal, financial, medical, or professional career advice. The optional wellbeing check-in feature is a personal tracking tool only. It is not a medical or mental-health service, is not monitored by us, and is not a substitute for professional help. If you are in crisis, contact a qualified professional or emergency services.</p>

  <h2>8. Acceptable use</h2>
  <p>You agree not to:</p>
  <ul class="body-list">
    <li>Use the Service in violation of any law or these Terms.</li>
    <li>Attempt to access another user&rsquo;s data or break the Service&rsquo;s per-user isolation or security.</li>
    <li>Reverse engineer, disrupt, overload, or probe the Service except as expressly permitted.</li>
    <li>Upload malicious code or content you have no right to share.</li>
    <li>Use the Service to generate deceptive, fraudulent, or harmful content.</li>
  </ul>
  <p>We may suspend or terminate access for conduct that violates these Terms.</p>

  <h2>9. Beta disclaimer</h2>
  <p>The Service is a beta. It is provided &ldquo;as is&rdquo; and &ldquo;as available,&rdquo; may contain errors, may change or be discontinued at any time, and may experience downtime or data issues. We recommend you keep your own copies of important materials. To the fullest extent permitted by law, we disclaim all warranties, express or implied, including merchantability, fitness for a particular purpose, and non-infringement.</p>

  <h2>10. Limitation of liability</h2>
  <p>To the fullest extent permitted by law, Frank MacBride will not be liable for any indirect, incidental, special, consequential, or punitive damages, or for lost profits, data, or goodwill, arising out of or related to your use of the Service. Our total liability for any claim will not exceed USD $100 or the amount you paid us in the twelve months before the claim, whichever is greater.</p>

  <h2>11. Indemnification</h2>
  <p>You agree to indemnify and hold harmless Frank MacBride from claims, damages, and expenses (including reasonable legal fees) arising from your use of the Service, Your Content, your handling of information about other people, or your violation of these Terms.</p>

  <h2>12. Third-party services</h2>
  <p>The Service relies on Microsoft (sign-in and hosting) and AI providers (Anthropic and OpenAI). Your use of those services through jobContext may also be subject to their terms. We are not responsible for third-party services.</p>

  <h2>13. Termination</h2>
  <p>You may stop using the Service and delete your account at any time. We may suspend or terminate your access at any time, including for violation of these Terms or to wind down the beta. On termination, the license you granted us ends and we will handle your data as described in the <a href="/privacy">Privacy Policy</a>.</p>

  <h2>14. Changes to these Terms</h2>
  <p>We may update these Terms as the Service evolves. If we make material changes, we will notify you through the Service or by email and update the effective date. Your continued use after an update means you accept the revised Terms.</p>

  <h2>15. Governing law</h2>
  <p>These Terms are governed by the laws of the State of Georgia, United States, without regard to its conflict-of-laws rules. You agree to the exclusive jurisdiction of the state and federal courts located in Georgia for any dispute.</p>

  <h2>16. Contact</h2>
  <p><a href="mailto:support@jobcontext.ai">support@jobcontext.ai</a><br>Frank MacBride</p>
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


def terms_html() -> str:
    return TERMS_HTML
