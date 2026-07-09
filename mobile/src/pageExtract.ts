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

export async function extractJobPage(url: string): Promise<string> {
  try {
    const ctrl = new AbortController()
    const timer = setTimeout(() => ctrl.abort(), 10000)
    const resp = await fetch(url, {
      signal: ctrl.signal,
      headers: { Accept: 'text/html' },
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

    // Fallback: og:title + stripped body, if the page looks substantive.
    const og = html.match(/<meta[^>]+property=["']og:title["'][^>]+content=["']([^"']+)/i)
    const body = STRIP(html)
    if (og && body.length > 500) {
      return `# ${og[1]}\n\n${body}`.slice(0, 60000)
    }
    return ''
  } catch {
    return ''
  }
}
