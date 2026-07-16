// On-device job-page extraction. The phone reads pages our cloud IPs can't:
// LinkedIn serves an authwall to datacenter egress but real content (with a
// JSON-LD JobPosting block) to residential connections. We fetch the shared
// URL here, distill it to clean text, and send it alongside the URL so the
// server never has to fetch at all. Best-effort: any failure returns '' and
// the server falls back to its own scrapers.

const STRIP = (html: string) =>
  html
    .replace(/<script[\s\S]*?<\/script>/gi, ' ')
    .replace(/<style[\s\S]*?<\/style>/gi, ' ')
    .replace(/<[^>]+>/g, ' ')
    .replace(/&amp;/g, '&')
    .replace(/&nbsp;/g, ' ')
    .replace(/&#?\w+;/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()

// LinkedIn serves its authwall to non-browser user agents even on
// residential IPs — the fetch must look like mobile Safari.
const BROWSER_HEADERS = {
  'User-Agent':
    'Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.5 Mobile/15E148 Safari/604.1',
  Accept: 'text/html,application/xhtml+xml',
  'Accept-Language': 'en-US,en;q=0.9',
}

const AUTHWALL_TITLE = /sign\s?up|sign\s?in|log\s?in|join linkedin|security verification/i

function isLinkedIn(url: string): boolean {
  try {
    return new URL(url).hostname.toLowerCase().includes('linkedin.com')
  } catch {
    return false
  }
}

// LinkedIn's guest job page carries stable anchors even when the JSON-LD
// block is absent (verified live 2026-07-10): the h1 top-card title, the
// org-name link, and the show-more-less description section.
function extractLinkedInMarkup(rawHtml: string): string {
  const html = rawHtml.replace(/\s+/g, ' ')
  const title = html.match(/<h1[^>]*top-card-layout__title[^>]*>([^<]+)/i)?.[1]?.trim()
  if (!title || AUTHWALL_TITLE.test(title)) return ''
  const org = html.match(/<a[^>]*topcard__org-name-link[^>]*>([^<]+)/i)?.[1]?.trim()
  const descRaw = html.match(/show-more-less-html__markup[^>]*>([\s\S]*?)<\/section>/i)?.[1] || ''
  const desc = STRIP(descRaw)
  if (desc.length < 100) return ''
  return [`# ${title}`, org ? `at ${org}` : '', desc].filter(Boolean).join('\n\n').slice(0, 60000)
}

export async function extractJobPage(url: string): Promise<string> {
  try {
    const ctrl = new AbortController()
    const timer = setTimeout(() => ctrl.abort(), 10000)
    const resp = await fetch(url, {
      signal: ctrl.signal,
      headers: BROWSER_HEADERS,
    })
    clearTimeout(timer)
    if (!resp.ok) return ''
    const html = await resp.text()

    // Prefer JSON-LD JobPosting — richest and unambiguous.
    const ldBlocks = html.match(
      /<script[^>]+application\/ld\+json[^>]*>([\s\S]*?)<\/script>/gi,
    )
    for (const block of ldBlocks || []) {
      try {
        const raw = block.replace(/^<script[^>]*>/i, '').replace(/<\/script>$/i, '')
        const ld = JSON.parse(raw)
        const nodes = Array.isArray(ld) ? ld : ld['@graph'] ? ld['@graph'] : [ld]
        for (const node of nodes) {
          if ((node?.['@type'] || '').toString().toLowerCase() !== 'jobposting') continue
          const title = (node.title || '').toString().trim()
          const company = (node.hiringOrganization?.name || '').toString().trim()
          const desc = STRIP((node.description || '').toString())
          if (title && desc.length > 100) {
            return [`# ${title}`, company ? `at ${company}` : '', desc]
              .filter(Boolean)
              .join('\n\n')
              .slice(0, 60000)
          }
        }
      } catch {
        // malformed block — try the next one
      }
    }

    // LinkedIn: structured markup parse (JSON-LD is often absent now).
    // Never fall through to og: for LinkedIn — an authwall page has an
    // og:title too and would import as junk.
    if (isLinkedIn(url)) {
      return extractLinkedInMarkup(html)
    }

    // Other hosts: og:title + stripped body, if the page looks substantive
    // and doesn't smell like a login interstitial.
    const og = html.match(/<meta[^>]+property=["']og:title["'][^>]+content=["']([^"']+)/i)
    const body = STRIP(html)
    if (og && body.length > 500 && !AUTHWALL_TITLE.test(og[1])) {
      return `# ${og[1]}\n\n${body}`.slice(0, 60000)
    }
    return ''
  } catch {
    return ''
  }
}
