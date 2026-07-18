/* LinkedIn CSV parsing per the design handoff's parser spec.

   parseCSV handles quoted fields, escaped quotes (""), embedded commas and
   newlines, and \r\n / \r / \n line endings; fully-empty rows are dropped.
   autoDetectMap matches lowercased headers (exact first, then substring),
   first match wins. LinkedIn's basic Shares.csv has no metric columns —
   those import as 0 and get filled in later via the Update sheet. */

export function parseCSV(text) {
  const rows = []
  let row = []
  let cur = ''
  let q = false
  for (let i = 0; i < text.length; i++) {
    const c = text[i]
    if (q) {
      if (c === '"') {
        if (text[i + 1] === '"') { cur += '"'; i++ } else q = false
      } else cur += c
    } else if (c === '"') {
      q = true
    } else if (c === ',') {
      row.push(cur); cur = ''
    } else if (c === '\n' || c === '\r') {
      if (c === '\r' && text[i + 1] === '\n') i++
      row.push(cur); rows.push(row); row = []; cur = ''
    } else {
      cur += c
    }
  }
  if (cur.length || row.length) { row.push(cur); rows.push(row) }
  return rows.filter((r) => r.length > 1 || (r[0] && r[0].trim()))
}

const DETECT = {
  text: ['sharecommentary', 'commentary', 'post text', 'text', 'content'],
  date: ['date', 'created'],
  imp: ['impressions', 'views'],
  rx: ['reactions', 'likes'],
  cm: ['comments'],
}

export function autoDetectMap(headerRow) {
  const head = headerRow.map((h) => h.trim().toLowerCase())
  const find = (names) => {
    for (const n of names) {
      const idx = head.findIndex((h) => h === n || h.includes(n))
      if (idx >= 0) return idx
    }
    return -1
  }
  return Object.fromEntries(Object.entries(DETECT).map(([k, names]) => [k, find(names)]))
}

export function extractHashtags(text) {
  return Array.from(String(text).matchAll(/#([\p{L}0-9_]+)/gu), (m) => m[1])
}

export function numCell(v) {
  const n = parseInt(String(v || '').replace(/[^0-9]/g, ''), 10)
  return Number.isNaN(n) ? null : n
}

export function fmtK(n) {
  n = +n || 0
  return n >= 1000 ? (n / 1000).toFixed(1).replace(/\.0$/, '') + 'k' : String(n)
}
