
# jobContext Branding

Unified brand system. The master kit lives in branding/kit/ and is the single
source of truth; the files below are derived copies wired into the app.

## The mark
A framed badge: a deep-navy disc (#0A0F1C) ringed in brand cyan (#00B5C8),
carrying the j (white) + C (cyan) monogram. Two variants:
- branding/kit/favicon.svg — no binary band. Use at small / UI sizes (favicons,
  nav, app header). This is the scalable mark, mirrored to
  branding/logo/jobcontextmcp-mark-dark.svg.
- branding/kit/jobcontext-patch.svg — adds the 00100100 binary band. Use only
  where it is legible (banners, OG image, large favicons).

Rule: only show the binary band when it is legible.

## Wordmark & lockup
- branding/kit/jobcontext-wordmark-dark.svg / -light.svg — "jobContext" text only.
- branding/kit/jobcontext-lockup.svg — mark + wordmark + tagline.
- branding/kit/jobcontext-ai-dark.svg / -light.svg — "jobContext.ai" wordmark.

## Banner
- branding/banner/banner.svg / .png — patch + wordmark + tagline. Used in the
  README header.

## Favicons & icons
- branding/favicon/favicon.svg, favicon-16.png, favicon-32.png
- branding/kit/icon-16/32/180/512.png — app icons (180 = apple-touch).

## Brand tokens
- Cyan primary: #00B5C8   - Navy ink: #0A0F1C → #0B1220
- Display type: Space Grotesk   - Mono: JetBrains Mono

## Where it's wired
- Runtime icons: transport/http/static/ (favicon.svg, favicon-16/32.png,
  apple-touch-icon.png, favicon.ico, og-image.svg/.png).
- In-product marks (framed badge): frontend Logo.jsx, landing, login,
  architecture, setup pages.
