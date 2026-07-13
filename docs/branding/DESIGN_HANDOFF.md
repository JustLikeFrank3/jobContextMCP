# jobContext — Graphics & Color Handoff

Complete inventory of every graphics asset and color scheme in the repo,
prepared for design refinement. Paths are repo-relative. Where two sources
disagree, the discrepancy is called out in §6 rather than silently resolved —
those are exactly the calls the designer should make.

Brand in one line: deep-navy ink surfaces, Miami-blue cyan primary
(**#00B5C8**), Space Grotesk display type, JetBrains Mono for code.

---

## 1. Graphics files

### 1.1 Brand kit (docs/branding/)

| File | Size / dims | What it is / where used |
|---|---|---|
| `docs/branding/logo/jobcontextmcp-mark.svg` | vector | The mark, light-background variant (navy #0F172A disc, cyan ring, j+C monogram) |
| `docs/branding/logo/jobcontextmcp-mark-dark.svg` | vector | The mark, dark-background variant — same art as the runtime favicon |
| `docs/branding/logo/jobcontextmcp-mark.png` / `-dark.png` | 400×400 | Raster exports of the two marks |
| `docs/branding/favicon/favicon.svg` | vector | Scalable favicon (no binary band) |
| `docs/branding/favicon/favicon-light.svg` | vector | Light-mode favicon variant |
| `docs/branding/favicon/favicon-16.png`, `-32.png` | 16², 32² | Raster favicons (dark) |
| `docs/branding/favicon/favicon-light-16.png`, `-32.png` | 16², 32² | Raster favicons (light) |
| `docs/branding/banner/banner.svg` / `.png` | 2560×560 | README header banner — patch + wordmark + tagline; includes the `00100100` binary band |
| `docs/branding/banner/jobcontextmcp-readme.svg` / `.png` | 1280×320 | Alternate/smaller README banner |

> `docs/branding/BRANDING.md` names a master kit at `branding/kit/`
> (wordmarks, lockup, patch, icon-16/32/180/512) as the single source of
> truth, but that directory is **not in this repo** — see §6.1.

### 1.2 Runtime web assets (transport/http/static/)

These are what the live site (jobcontext.ai) actually serves.

| File | Size / dims | Usage |
|---|---|---|
| `favicon.svg` | vector | Browser favicon (identical art to mark-dark) |
| `favicon-16.png`, `favicon-32.png` | 16², 32² | Raster favicons |
| `favicon.ico` | 256×256 multi | Legacy favicon |
| `apple-touch-icon.png` | 180×180 | iOS home-screen icon |
| `og-image.svg` / `.png` | 1200×627 | Social/OpenGraph card (navy gradient, mark, wordmark, tagline) |

### 1.3 App icons

| File | Size / dims | Usage |
|---|---|---|
| `desktop/icon-source.png` | 512×512 | Source for Tauri desktop icon generation (`tauri icon`) — platform icons are generated at build time, not checked in |
| `mobile/assets/icon.png` | 512×512 | Expo app icon (same art as desktop source). `mobile/app.json` sets splash/background color `#0b1117` |

### 1.4 In-product mark (inline SVG, not files)

The framed-badge mark is also drawn inline in code — any redesign of the
mark must be propagated to these:

- `frontend/src/design-system/Logo.jsx` (dashboard SPA header)
- Server-rendered pages: `transport/http/routes/landing.py` (~line 412,
  360×360 circle `#0A0F1C`), `login_page.py`, `architecture.py`,
  `setup.py`, `why.py`
- `desktop/splash/index.html` (splash screen)

### 1.5 Screenshots / demo renders (reference only, not brand assets)

- `docs/jobContextMCP Dashboard v1.png` (1919×956), `v2.png` (1920×1080) — dashboard UI reference
- `docs/screenshots/template-{executive,modern,portfolio,sidebar}.png` — resume template previews
- `docs/demo/demo_resume_*.png`, `docs/demo/demo_coverletter_*.png` — rendered document samples (all 5 templates)
- `docs/legacy-resume-preview.png`, `docs/legacy-cl-preview.png` — legacy template previews
- `desktop/src-tauri/dmg-background.tiff` — macOS DMG installer background

---

## 2. Core brand tokens

From `docs/branding/BRANDING.md`:

| Token | Value |
|---|---|
| Cyan primary ("Porsche Miami Blue") | `#00B5C8` |
| Navy ink (bg gradient) | `#0A0F1C` → `#0B1220` |
| Display / UI type | Space Grotesk |
| Mono type | JetBrains Mono |

---

## 3. Product UI palettes (dark theme)

### 3.1 Dashboard SPA design tokens — `frontend/src/design-system/tokens.css`

The stated source of truth for the React dashboard. (`frontend/src/styles/global.css`
only consumes these tokens.)

**Cyan (primary):** `--cyan-500 #00B5C8` (primary) · `--cyan-400 #22C7E0` · `--cyan-300 #6FE0EE`

**Green (success):** `--green-500 #22C55E` · `--green-300 #7BE6A4`

**Semantic:** `--danger #EF4444` · `--danger-soft #F87171` · `--warn #F59E0B`

**Ink / surfaces:**
`--ink-900 #0A0F1C` (bg top) · `--ink-850 #0B1220` (bg bottom) · `--ink-700 #141E33` ·
`--ink-600 #1C2740` (tracks) · `--ink-500 #2A3954` (toggle-off) ·
`--surface #111A2B` · `--surface-raised #16213A` · `--surface-sunken #1B2A44` · `--surface-chip #22324E`

**Lines:** `--border #23324D` · `--border-soft #1A2740` · `--line-strong #2E4366`

**Text:** `--text #F2F6FC` · `--text-strong #FFFFFF` · `--text-soft #D7E3F8` ·
`--muted #9AA8BF` · `--faint #6B7A93`

Non-color tokens the designer may care about: radii 6/8/10/12/14 px + pill;
font sizes 0.7–1.6 rem scale; weights 400/500/600/700; shadow
`0 6px 20px rgba(0,0,0,.35)`; cyan glow ring; motion 120/160/240 ms.

### 3.2 Landing / marketing palette — `transport/http/routes/landing.py`

A newer "redesign" ramp that **extends** 3.1 (same core values, more stops).
Its header comment says it's anchored on the brand sheet: deep navy ink,
vivid cyan `#00B5C8`, confirmation green `#22C55E`, warm slate neutrals.

**Ink ramp:** `--ink-950 #070B14` · `--ink-900 #0A0F1C` · `--ink-850 #0B1220` ·
`--ink-800 #0F172A` (brand navy, hero/sidebar) · `--ink-700 #111A2B` ·
`--ink-600 #16213A` · `--ink-500 #1B2A44` · `--ink-450 #22324E`

**Cyan ramp:** `--cyan-700 #0673A6` · `--cyan-600 #0894AE` · `--cyan-500 #00B5C8` ·
`--cyan-400 #22C7E0` · `--cyan-300 #6FE0EE` · `--cyan-100 #D1FBFB`

**Green:** `--green-600 #16A34A` · `--green-500 #22C55E` · `--green-300 #7BE6A4`

**Slate neutrals:** `--slate-700 #1E293B` · `--slate-600 #334155` · `--slate-400 #64748B`

**Text / lines:** same as 3.1, plus `--on-primary #062330` (dark ink on cyan
buttons) and `--on-success #052E16`.

**Semantic:** `--danger #EF4444` · `--danger-soft #F87171` · `--warn #F59E0B` ·
`--ok #22C55E` · `--info #00B5C8`

Decorative extras in the page: mock window-chrome dots `#FF5F57 / #FEBC2E / #28C840`,
code-block bg `#062330`.

### 3.3 Server-rendered dashboard pages — `transport/http/routes/dashboard/shared.py`

Duplicates the 3.1 values as an inline stylesheet (plus `#0F172A` and
`#062330` accents) for all `transport/http/routes/dashboard/*.py` pages
(pipeline, posts, interviews, materials, settings, etc.). Any palette change
must be made here **and** in tokens.css — they are separate copies.

### 3.4 Mobile theme — `mobile/src/theme.ts`

Comment claims it "mirrors the dashboard SPA's dark theme" but the values
are a different (GitHub-dark-flavored) palette — see §6.2:

`bg #0B1117` · `surface #111A24` · `surfaceRaised #16222F` · `border #223049` ·
`text #E6EDF3` · `muted #8B949E` · `faint #5C6873` · `cyan #00B5C8` ·
`cyanSoft #66D5E0` · `green #3FB950` · `danger #F85149`

(`mobile/app.json` splash/adaptive-icon background: `#0B1117`.)

### 3.5 Desktop splash — `desktop/splash/index.html`

`bg #0B1220` · `text #E6EDF5` · accent/spinner `#00B5C8` · text-on-cyan `#06222A`

---

## 4. Document template color schemes (resume + cover letter)

Light-background print/PDF palettes, unrelated to the product's dark UI.

### 4.1 Selectable themes — `templates/resume_templates/themes/*.css`

Each defines the same 12 variables: `--accent, --accent-light, --accent-mid,
--accent-dark, --heading, --rule, --sidebar-bg, --sidebar-text,
--sidebar-head, --chip-bg, --chip-text, --link`.

| Theme | accent | accent-light | accent-dark | heading | sidebar-bg | sidebar-text | sidebar-head | chip-bg | chip-text | link |
|---|---|---|---|---|---|---|---|---|---|---|
| **classic** (B&W, max ATS) | `#111111` | `#444444` | `#000000` | `#111111` | `#1A1A1A` | `#F0F0F0` | `#BBBBBB` | `#EEEEEE` | `#222222` | `#333333` |
| **navy** (deep professional blue) | `#1E3A5F` | `#2D5A9E` | `#0F1E35` | `#1E3A5F` | `#1E3A5F` | `#E8EEF8` | `#A8C0E8` | `#DDE8F8` | `#1E3A5F` | `#2D5A9E` |
| **warm** (amber / golden brown) | `#92400E` | `#B45309` | `#5C2D09` | `#78350F` | `#7C2D12` | `#FEF3C7` | `#FBBF24` | `#FEF3C7` | `#78350F` | `#B45309` |
| **slate** (cool gray-blue) | `#334155` | `#475569` | `#1E293B` | `#1E293B` | `#334155` | `#E2E8F0` | `#94A3B8` | `#E2E8F0` | `#334155` | `#475569` |
| **forest** (deep green) | `#1A6644` | `#2D9E6A` | `#0F3D28` | `#1A6644` | `#1A6644` | `#E6F4EE` | `#8FD4B0` | `#D4F0E2` | `#1A6644` | `#2D9E6A` |

(accent-mid, omitted above: classic `#222222`, navy `#26487A`, warm `#A24E10`,
slate `#3D4F63`, forest `#1F7A50`. rule: classic `#666666`, navy `#1E3A5F`,
warm `#B45309`, slate `#475569`, forest `#1A6644`.)

### 4.2 Built-in defaults per template — `templates/resume_templates/*/styles.css`

Each template also hard-codes a default accent (used when no theme applies —
and duplicated in the matching `templates/cover_letter_templates/*` and the
`resume.html`/`cover_letter.html` files):

| Template | Hard-coded accent | Notes |
|---|---|---|
| **modern** | `#1E3A5F` | = navy theme accent; neutral grays `#1A1A1A/#333/#444/#555` |
| **executive** | `#1A2744` | darker navy, **not** in any theme file; light panel `#F7F8FA` |
| **portfolio** | `#1A6644` | = forest theme accent; tints `#F2F8F5`, `#B5D9C8` |
| **sidebar** | `#1E3A5F` | = navy theme; sidebar tints `#E8EDF2 #D0DCE8 #A8C0D6 #7AA5C8 #2D5580` |
| **legacy** (`templates/cover_letter.html`) | grayscale | plain black-on-white |

---

## 5. Typography

- **Space Grotesk** (300–700) — display and UI text everywhere (dashboard, landing, marketing pages). Loaded from Google Fonts.
- **JetBrains Mono** (400–700) — code, terminal mock-ups, binary band in the banner.
- Templates/PDF: system serif/sans stacks per template (see each `styles.css`).

---

## 6. Known inconsistencies (designer's call)

1. **Missing master kit.** `BRANDING.md` points to `branding/kit/` as the
   single source of truth (wordmarks, lockup, patch, icon set). It is not in
   the repo — only the derived copies under `docs/branding/` and
   `transport/http/static/` exist. The refined kit should either be added at
   that path or BRANDING.md updated.
2. **Mobile palette drift.** `mobile/src/theme.ts` says it mirrors the SPA but
   uses different values: bg `#0B1117` vs `#0A0F1C`, text `#E6EDF3` vs
   `#F2F6FC`, green `#3FB950` vs `#22C55E`, danger `#F85149` vs `#EF4444`,
   muted `#8B949E` vs `#9AA8BF`. Decide which is canonical.
3. **Two cyan stories.** `tokens.css` notes a handoff spec listed `#06B6D4`
   as cyan-500 but the live brand is `#00B5C8` (kept). `landing.py`'s comment
   confusingly says the "muted teal #00B5C8 is retired" while still using
   `#00B5C8` as primary. One consolidated statement of the cyan ramp
   (including landing's extra `#0673A6/#0894AE/#D1FBFB` stops, absent from
   tokens.css) would end the ambiguity.
4. **Palette duplication.** The dark-UI palette lives in at least four
   places that must be kept in sync by hand: `tokens.css`,
   `dashboard/shared.py`, `landing.py` (and siblings: login, setup, why,
   architecture, privacy, terms, oauth), and `mobile/src/theme.ts`.
   Template accents are likewise duplicated between `themes/*.css`, each
   template's `styles.css`, and the HTML files.
5. **On-cyan ink varies.** Text-on-cyan is `#062330` (landing), `#06222A`
   (desktop splash) — near-identical but not equal.
