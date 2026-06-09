#!/usr/bin/env python3
"""
gen_demo_docs.py
----------------
Generates a fake-but-realistic resume + cover letter in LaTeX/PDF format
for screenshot / marketing purposes.

Run from the jobContextMCP root:
    python scripts/gen_demo_docs.py
"""

import sys
from pathlib import Path

# ── make sure the package root is importable ───────────────────────────────
_HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_HERE))

from tools.resume import save_resume_txt, save_cover_letter_txt
from tools.export import export_cover_letter_pdf
from tools.latex_export import generate_cover_letter_latex, generate_resume_latex


DEMO_COMPANY = "Aperture AI"
DEMO_ROLE = "AI Engineer"
DEMO_RESUME_FILENAME = "Demo Nobody MacFakename - Aperture AI Engineer.txt"
DEMO_COVER_LETTER_FILENAME = "Demo Nobody MacFakename - Aperture AI Cover Letter.txt"


# ── FAKE RESUME ────────────────────────────────────────────────────────────
# Written to match the strict .txt format spec that export.py parses.

FAKE_RESUME = """\
<NOBODY MACFAKENAME>
NOBODY MACFAKENAME

phone: +1 (555) 010-4242
email: nobody.macfakename@example.com
linkedin: www.linkedin.com/in/nobody-macfakename
github: github.com/nobody-macfakename

AI Engineer | LLM Systems • RAG • Agents • Python • MLOps

Nobody is an AI engineer with seven years of experience building LLM-powered
applications, retrieval systems, evaluation harnesses, and model-serving
infrastructure. Known for turning ambiguous product ideas into observable,
privacy-aware AI workflows that teams can ship, measure, and improve.

──────────────────────────────────────────────────────────

CORE TECHNICAL SKILLS

Languages: Python, TypeScript, SQL, Bash, Java
AI/ML: LLMs, RAG, prompt engineering, embeddings, evals, PyTorch, scikit-learn
Frameworks: FastAPI, LangGraph, LangChain, React, Next.js, Spring Boot
Cloud & Infra: AWS, Docker, Terraform, GitHub Actions, Kubernetes, Tectonic
Data & Search: PostgreSQL, Redis, Kafka, pgvector, OpenSearch, BigQuery
Observability: OpenTelemetry, Datadog, Sentry, prompt traces, model-quality dashboards

──────────────────────────────────────────────────────────

PROFESSIONAL EXPERIENCE

Senior AI Engineer | Aperture AI, Remote | March 2023 - Present
• Built a retrieval-augmented research assistant over 8.6 M internal documents,
  improving grounded-answer acceptance from 61 % to 89 % while cutting median
  response latency from 9.4 s to 3.1 s.
• Designed an LLM evaluation harness with golden datasets, rubric scoring, and
  regression gates; reduced hallucination incidents by 43 % across three releases.
• Shipped an agentic workflow for support triage that resolves 31 % of inbound
  tickets without escalation and preserves a complete audit trail for reviewers.
• Added OpenTelemetry tracing for prompts, retrieval spans, and tool calls,
  reducing mean time to diagnose production AI failures from 42 minutes to 8 minutes.

Machine Learning Engineer | ModelWorks Studio, Chicago, IL | July 2020 - February 2023
• Productionized a document-classification pipeline serving 2.3 M files per day
  with 99.95 % uptime and a 27 % reduction in manual review volume.
• Implemented embedding search with pgvector and OpenSearch hybrid ranking,
  increasing top-5 retrieval precision from 72 % to 91 % on internal benchmarks.
• Partnered with security and legal teams to add PII redaction, prompt logging,
  and data-retention controls for regulated customer workflows.

Software Engineer | Signal Orchard, Austin, TX | August 2017 - June 2020
• Built Python and TypeScript services for analytics products used by 120 k
  monthly active users, improving API p95 latency from 820 ms to 190 ms.
• Created a feature-flag and experiment platform that supported 46 controlled
  launches and helped product teams measure adoption without ad hoc SQL pulls.
• Automated PDF report generation with LaTeX, Tectonic, and template rendering,
  reducing weekly analyst preparation time from 14 hours to 90 minutes.

EDUCATION

B.S. Computer Science | Fictional State University, Faketown, CA | 2017

──────────────────────────────────────────────────────────

LEADERSHIP & CERTIFICATIONS

AWS Certified Machine Learning – Specialty (2024)
Open-source contributor: prompt-eval fixtures, pgvector utilities, LangGraph examples
Speaker, Synthetic Systems Meetup — Practical Evals for Production AI (2025)
</NOBODY MACFAKENAME>
"""


# ── FAKE COVER LETTER BODY ─────────────────────────────────────────────────
# Plain prose, 4 paragraphs — the LaTeX pipeline supplies salutation + sign-off.

FAKE_COVER_LETTER_BODY = """\
I have spent the last seven years turning uncertain AI ideas into systems people can actually trust: search that cites its sources, agents that leave an audit trail, and evaluation suites that catch regressions before customers do. Aperture AI's focus on practical, reliable AI tools is exactly the kind of engineering problem I want to work on next. The role stood out because it treats model quality, product usefulness, and production operations as one system rather than three separate concerns.

At Aperture AI I built a retrieval-augmented research assistant over 8.6 million internal documents. The first version had useful demos but uneven production behavior: answers were slow, retrieval quality was hard to explain, and failures disappeared into generic logs. I rebuilt the retrieval pipeline, added hybrid ranking, introduced source-grounded response checks, and instrumented prompt, retrieval, and tool-call spans with OpenTelemetry. Grounded-answer acceptance rose from 61 percent to 89 percent, median response latency dropped from 9.4 seconds to 3.1 seconds, and mean time to diagnose production AI failures fell from 42 minutes to 8 minutes.

That pattern shows up across my work. I designed an LLM evaluation harness with golden datasets, rubric scoring, and release gates that reduced hallucination incidents by 43 percent across three releases. At ModelWorks Studio I productionized a document-classification pipeline serving 2.3 million files per day at 99.95 percent uptime, then improved top-5 retrieval precision from 72 percent to 91 percent with pgvector and OpenSearch hybrid ranking. Earlier, at Signal Orchard, I automated PDF report generation with LaTeX, Tectonic, and template rendering, reducing weekly analyst preparation time from 14 hours to 90 minutes.

Aperture AI looks like the right place to keep doing that kind of work: close enough to product to know whether the AI is useful, close enough to infrastructure to make it dependable, and disciplined enough to measure the difference. I would enjoy talking through how my experience with RAG, evals, observability, and document automation could help your team ship reliable AI systems faster.
"""

FAKE_COVER_LETTER_TXT = f"""\
Nobody MacFakename
phone: +1 (555) 010-4242
email: nobody.macfakename@example.com
linkedin: www.linkedin.com/in/nobody-macfakename
github: github.com/nobody-macfakename

Aperture AI
AI Engineer

Dear Hiring Manager,

{FAKE_COVER_LETTER_BODY.strip()}

Kindest Regards,
Nobody MacFakename
"""

DEMO_IDENTITY = {
    "name": "Nobody MacFakename",
    "phone": "+1 (555) 010-4242",
    "city": "Faketown, CA",
    "email": "nobody.macfakename@example.com",
    "linkedin": "nobody-macfakename",
    "github": "nobody-macfakename",
}


# ── MAIN ──────────────────────────────────────────────────────────────────

def main() -> None:
    print("─── Generating demo resume ───")
    resume_filename = DEMO_RESUME_FILENAME
    saved_resume = save_resume_txt(resume_filename, FAKE_RESUME)
    print(f"  saved: {saved_resume}")

    resume_pdf = generate_resume_latex(
        resume_text=FAKE_RESUME,
        company=DEMO_COMPANY,
        role=DEMO_ROLE,
        role_title=DEMO_ROLE,
        output_filename="Demo Nobody MacFakename - Aperture AI Engineer.pdf",
        identity=DEMO_IDENTITY,
    )
    print(f"  pdf (LaTeX): {resume_pdf}")

    print("\n─── Generating demo cover letter (LaTeX) ───")
    cl_filename = DEMO_COVER_LETTER_FILENAME
    saved_cl = save_cover_letter_txt(cl_filename, FAKE_COVER_LETTER_TXT)
    print(f"  saved: {saved_cl}")

    try:
        latex_pdf = generate_cover_letter_latex(
            body=FAKE_COVER_LETTER_BODY,
            company=DEMO_COMPANY,
            role=DEMO_ROLE,
            role_title=DEMO_ROLE,
            identity=DEMO_IDENTITY,
        )
        print(f"  pdf (LaTeX): {latex_pdf}")
    except (RuntimeError, FileNotFoundError) as exc:
        print(f"  LaTeX pipeline unavailable ({exc}), falling back to HTML/weasyprint…")
        html_pdf = export_cover_letter_pdf(cl_filename, footer_tag="AI ENGINEER")
        print(f"  pdf (HTML): {html_pdf}")

    print("\n✓ Done.")


if __name__ == "__main__":
    main()
