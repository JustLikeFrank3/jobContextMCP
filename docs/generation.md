# Document Generation — Resumes, Cover Letters, PDF Export

`documents(action="generate_resume")` and `documents(action="generate_cover_letter")` are end-to-end tools: one call produces a saved `.txt` + exported PDF. They load the master resume, tone profile, and job-fitment strategy automatically — no manual context assembly.

## Two modes

**With an LLM configured** (OpenAI key, Azure AI Foundry, Anthropic BYOK, or local Ollama): the tool generates content, saves the `.txt`, exports the PDF, and reports token/cost. Provider resolution goes through `lib/config.get_llm_client()`; all calls funnel through `lib/openai_calls.create_chat_completion` (rate-spacing, retry handling).

**Without a key**: each tool returns a full context package — master resume, tone profile, customization strategy, and format instructions — and the calling AI client (Copilot, Claude) writes the content itself, then calls `documents(action="save_resume")` / `documents(action="export_resume_pdf")`.

There's also an agentic pipeline, `documents(action="generate_resume_agent")` — a LangGraph `StateGraph` (`load_context → retrieve → draft → review → (revise → review){0..N} → output`) with per-node SSE progress streaming via `POST /workflows/resume/stream`. Higher-quality output than a single LLM call.

## The provenance gate

Every generation and AI-edit path runs a deterministic truth gate (`lib/provenance.py`): numeric claims in a draft (percentages, dollar amounts, magnitudes, years) must exist in the run's source material — the master-context bundle (master resume + achievements + peer feedback + stories), STAR stories, JD — or the agent pipeline routes back for revision. Retrieved RAG chunks are deliberately **not** evidence: the index ingests previously generated documents, so counting chunks as sources let past fabrications certify their own reappearance (citogenesis, found 2026-08 — a fossilized chunk count survived in generated resumes for weeks because each generation's gate accepted the previous generation's output as proof). Chunks still steer *emphasis* in the agent pipeline's draft prompt; they can no longer make a claim count as true. LLM reviewer approval alone is never sufficient. Every run writes an audit record (`generation_provenance`); edits to the master resume itself are audited too (`master_resume_edits`), so the gate's ground truth can't drift invisibly. The verdict surfaces as a one-line summary in every confirmation and a pass/fail badge in the dashboard; failures open a violations modal with per-claim **Fix** / **Fix all** actions that hand off to the AI-edit flow (which re-runs the gate).

## Prompt budgeting & story retrieval

**Resume prompts are bundle-first (2026-08-14):** the personal-story library rides *inside* the master-context bundle as a STORIES section (`lib.io._load_master_context`), not as a separately retrieved block. One evidence document means the provenance gate (whose sources are the prompt) and the eval judge (which reads the same bundle) verify against exactly what the generator saw. When the full bundle would blow the prompt ceiling, the STORIES section is trimmed tail-first and deterministically — whole stories, file order, never query-ranked — so the generator's evidence is always an exact prefix of the judge's. Tone samples are bounded and explicitly style-only: the system prompts forbid treating a fact that appears only in a tone sample as evidence.

Cover-letter generation still pulls relevant personal stories from your personal context library for the opening hook; for mission/brand-heavy roles it uses semantic story retrieval (cached embeddings + hook-tag boosts) so abstract company language finds the strongest human angle instead of only matching literal keywords. That selection is emphasis, not extra evidence — every retrievable story is also in the bundle the judge reads. Scraped JDs are cleaned before prompting so LinkedIn navigation chrome doesn't crowd out the actual posting.

Optional `generation_budgets` config keys bound each section. To activate semantic story retrieval, run `materials(action="reindex_stories")` once after ingesting stories, and again whenever you add new ones.

## Personas

`services/persona_service.py` loads JSON persona presets from `data/personas/` (bundled: `default`, `executive_polish`, `faang_technical`, `startup_founder`); drop your own JSON into `<data_folder>/personas/` to override. Each persona contributes a prompt block (tone modifiers, weighting, formatting rules). Personas apply to both generation and fitment assessment — the same JD through `faang_technical` weighs systems depth; `executive_polish` weighs leadership narrative; `startup_founder` weighs ownership and range. Unknown persona names warn rather than crash.

## Format constraints (enforced in the prompts)

**Resume**
- All metrics and achievements must come verbatim from your master resume — no invention (and the provenance gate checks).
- Section headers ALL CAPS: `PROFESSIONAL EXPERIENCE`, `CORE TECHNICAL SKILLS`, `EDUCATION`, `LEADERSHIP & COMMUNITY`.
- Job header format: `Title | Company, Location | Month YYYY - Month YYYY`.
- Bullets use `•` (U+2022) — not `-` or `*`.
- Contact block uses labeled fields: `phone:`, `email:`, `linkedin:`.
- Target length: 650–800 words.

**Cover letter**
- 380–430 words in the body; exactly 4 paragraphs (hook + role / technical achievement + metric / differentiators / closer).
- No address block, no Re: line; salutation is `Dear Hiring Manager,`.
- Prose only — no bullets, bold, or headers in the body.

These constraints are baked into the prompts; deviations cause PDF rendering errors because the templates have fixed dimensions. If you add your own generation logic, copy the format specs from `tools/generate_prompts.py`.

## PDF export & templates

PDFs render from plain `.txt` files via WeasyPrint — no design tools. 4 layouts (`modern`, `executive`, `sidebar`, `portfolio`) × 5 themes (`navy`, `slate`, `forest`, `warm`, `classic`) = 20 variants, all consuming the same data model. Template and theme are selected per-job in the pipeline and persist in SQLite. Cover letters have a matching 4-layout system.

```python
from tools.export import export_resume_pdf
export_resume_pdf("Your Resume.txt", template="sidebar", style="slate")
```

If no template preference is saved, output falls back to the legacy format — Courier New, monospaced, hacker-tag header/footer. Select a template in the pipeline and this will never happen to you.

On macOS, WeasyPrint needs native libs: `brew install cairo pango gdk-pixbuf libffi`. Docker images include them.

## Feeding the system

`insights(action="session_context")` loads four things every session: master resume, tone profile, personal context library, and live pipeline. It does **not** read individual resumes or cover letters — anything meaningful that lives only in those files is invisible until you extract and log it. **This is the most common reason for generic output.**

Before relying on the system:

1. **Scan existing materials for tone samples** — `stories(action="tone_scan")` on your cover letters and resumes, once after setup and again after adding batches of new material.
2. **Log personal stories explicitly** — `stories(action="log")` for anything worth keeping from old cover letters, going-away cards, award citations, performance reviews.
3. **Ingest peer feedback verbatim** — peer-sourced, manager-attributed language is more credible in interviews than anything you write about yourself.
4. **Rebuild the RAG index after adding files** — `materials(action="reindex")`; it is not automatic.
5. **Scan side projects after any sprint** — `brand(action="scan_project_skills")` reads the codebases listed in `side_project_folders` in `config.json` and surfaces resume bullets you haven't written yet.

When in doubt: if something made you proud, surprised a colleague, landed in a card, or earned a recognition — log it.
