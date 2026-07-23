// Shared cross-domain data layer for detail pages, global search, and the
// timeline. The cloud API only exposes per-domain listing payloads (no
// per-object GET), so every "detail" view hydrates from these lists and the
// relationships are joined client-side by company name. One short-lived
// cache keeps a tab full of detail pushes from re-fetching five endpoints
// per screen; pull-to-refresh forces through it.
import { api, InboxEvent } from '../api'

export type Job = {
  id: number
  company: string
  role: string
  status?: string
  source?: string
  added_date?: string
  fitment_score?: string | number | null
  decision_notes?: string
  assessed?: boolean
  assessment_summary?: string
  assessment_detail?: string
  recommended_resume?: string
  selected_resume?: string
  last_edited_resume?: string
  last_edited_cover_letter?: string
}

export type Quote = string | { speaker?: string; quote?: string }
export type Interview = {
  id?: number
  company?: string
  role?: string
  interview_date?: string
  interview_type?: string
  interviewer?: string
  interviewer_role?: string
  self_rating?: number | null
  what_landed?: string[]
  what_didnt?: string[]
  verbatim_quotes?: Quote[]
  upcoming?: boolean // set client-side from which payload bucket it came in
}

export type Person = {
  id: number
  name: string
  relationship?: string
  company?: string
  context?: string
  contact_info?: string
  outreach_status?: string
  notes?: string
  tags?: string[]
  last_updated?: string
  last_contacted?: string
}

export type Post = {
  id: number
  text: string
  title?: string
  source?: string
  posted_date?: string
  url?: string
  hashtags?: string[]
  impressions: number
  reactions: number
  comments: number
}

export type Checkin = {
  date: string
  mood?: string
  energy?: number
  notes?: string
  productive?: boolean
}

export type Datasets = {
  jobs: Job[]
  interviews: Interview[]
  people: Person[]
  posts: Post[]
  postTotals: { impressions: number; reactions: number; comments: number }
  checkins: Checkin[]
  events: InboxEvent[]
}

const TTL_MS = 60_000
let cache: { at: number; data: Datasets } | null = null
let inflight: Promise<Datasets> | null = null

/** Fetch every domain the app knows about. Sections fail independently —
 *  a broken endpoint empties its slice instead of sinking the whole page —
 *  but if literally everything failed, surface the first error. */
export async function loadDatasets(force = false): Promise<Datasets> {
  if (!force && cache && Date.now() - cache.at < TTL_MS) return cache.data
  if (inflight) return inflight
  inflight = (async () => {
    const [jobsR, ivR, peopleR, postsR, healthR, eventsR] = await Promise.allSettled([
      api<{ jobs: Job[] }>('/dashboard/pipeline/data'),
      api<{ upcoming: Interview[]; recent: Interview[] }>('/dashboard/interviews/data'),
      api<{ people?: Person[]; recent: Person[] }>('/dashboard/people/data'),
      api<{
        posts: Post[]
        total_impressions: number
        total_reactions: number
        total_comments: number
      }>('/dashboard/posts/data'),
      api<{ recent: Checkin[] }>('/dashboard/health/data'),
      api<{ events: InboxEvent[] }>('/api/events'),
    ])
    const settled = [jobsR, ivR, peopleR, postsR, healthR, eventsR]
    if (settled.every((r) => r.status === 'rejected')) {
      throw (settled[0] as PromiseRejectedResult).reason
    }
    const iv = ivR.status === 'fulfilled' ? ivR.value : { upcoming: [], recent: [] }
    const posts = postsR.status === 'fulfilled' ? postsR.value : null
    const people = peopleR.status === 'fulfilled' ? peopleR.value : null
    const data: Datasets = {
      jobs: jobsR.status === 'fulfilled' ? jobsR.value.jobs || [] : [],
      interviews: [
        ...(iv.upcoming || []).map((i) => ({ ...i, upcoming: true })),
        ...(iv.recent || []).map((i) => ({ ...i, upcoming: false })),
      ],
      people: people ? (people.people?.length ? people.people : people.recent) || [] : [],
      posts: posts?.posts || [],
      postTotals: {
        impressions: posts?.total_impressions || 0,
        reactions: posts?.total_reactions || 0,
        comments: posts?.total_comments || 0,
      },
      checkins: healthR.status === 'fulfilled' ? healthR.value.recent || [] : [],
      events: eventsR.status === 'fulfilled' ? eventsR.value.events || [] : [],
    }
    cache = { at: Date.now(), data }
    return data
  })()
  try {
    return await inflight
  } finally {
    inflight = null
  }
}

export const normName = (s?: string) => (s || '').trim().toLowerCase()

/** Everything the app knows about one company, joined by name. */
export type CompanyBundle = {
  name: string
  jobs: Job[]
  interviews: Interview[]
  people: Person[]
  events: InboxEvent[]
}

export function companyBundle(ds: Datasets, name: string): CompanyBundle {
  const key = normName(name)
  return {
    name,
    jobs: ds.jobs.filter((j) => normName(j.company) === key),
    interviews: ds.interviews.filter((i) => normName(i.company) === key),
    people: ds.people.filter((p) => normName(p.company) === key),
    events: ds.events.filter((e) => normName(e.company) === key),
  }
}

/** Distinct companies across all domains, most-connected first. */
export function allCompanies(ds: Datasets): string[] {
  const seen = new Map<string, { name: string; count: number }>()
  const add = (name?: string) => {
    const key = normName(name)
    if (!key) return
    const cur = seen.get(key)
    if (cur) cur.count += 1
    else seen.set(key, { name: (name || '').trim(), count: 1 })
  }
  ds.jobs.forEach((j) => add(j.company))
  ds.interviews.forEach((i) => add(i.company))
  ds.people.forEach((p) => add(p.company))
  return [...seen.values()].sort((a, b) => b.count - a.count).map((c) => c.name)
}

/** Whole days elapsed since an ISO-ish date string; null when unparsable. */
export function daysSince(dateStr?: string): number | null {
  const m = String(dateStr || '').match(/^(\d{4})-(\d{2})-(\d{2})/)
  if (!m) return null
  const then = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]))
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  return Math.round((today.getTime() - then.getTime()) / 86400000)
}

/** Email / phone / LinkedIn URL mined from a contact's free-text fields. */
export function contactChannels(p: Person) {
  const info = `${p.contact_info || ''} ${p.notes || ''} ${p.context || ''}`
  const email = info.match(/[\w.+-]+@[\w-]+\.[\w.]+/)?.[0]
  const phone = info.match(/\+?1?[\s.-]?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}/)?.[0]
  const linkedin = info.match(/(?:https?:\/\/)?(?:www\.)?linkedin\.com\/[^\s,)]+/i)?.[0]
  return { email, phone, linkedin }
}
