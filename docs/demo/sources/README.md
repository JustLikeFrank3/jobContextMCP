# Demo sources

Fully fictional resume and cover-letter text used to render the README demo
gallery in [`docs/demo/`](../). **No real contact information** — safe to commit.

- `Nobody-MacFakename-Demo-Resume.txt`
- `Nobody-MacFakename-Demo-Cover-Letter.txt`

These are the canonical inputs the demo generator renders into the PDFs and PNGs
under `docs/demo/`. Editing them and re-rendering is how the gallery is
refreshed.

## Why the contact header matters

Both files begin with a self-contained contact header (fake name, phone, email,
LinkedIn, GitHub, city). **That header is required.** Without it, the
cover-letter parser (`lib/resume_parser._parse_cover_letter_txt`) treats the
salutation as the name and falls back to `config.json` for contact fields —
which would leak the repo owner's real LinkedIn/email into every rendered demo.
Keep the header intact when editing these fakes.
