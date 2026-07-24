// Executive-summary sentences for every detail page, composed on-device
// from the joined datasets. Deterministic heuristics, not an LLM call: the
// cloud has no summary endpoint yet, and the phone already holds every fact
// these sentences state (counts, gaps, scores, relationships). When a server
// endpoint exists, detail pages can prefer it and keep this as the offline
// fallback.
import {
  Checkin,
  CompanyBundle,
  Datasets,
  Interview,
  Job,
  Person,
  Post,
  Quote,
  companyBundle,
  contactChannels,
  daysSince,
  normName,
} from './store'

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? '' : 's'}`

function quoteText(q?: Quote): string {
  if (!q) return ''
  return typeof q === 'string' ? q : q.quote || ''
}

export function jobSummary(job: Job, ds: Datasets): string[] {
  const out: string[] = []
  const score = Number(job.fitment_score) || 0
  const status = (job.status || 'pending').toLowerCase()
  const co = companyBundle(ds, job.company)

  if (score >= 85) out.push(`Excellent fit — this role scores ${score}, near the top of your pipeline.`)
  else if (score >= 75) out.push(`Solid fit at ${score} — worth pursuing with a tailored resume.`)
  else if (score > 0) out.push(`Moderate fit at ${score} — weigh it against stronger openings before investing time.`)
  else out.push('Not yet assessed — run the assessment to get a fit score and recommendation.')

  const age = daysSince(job.added_date)
  if (status === 'applied') out.push(`You applied${age != null ? ` ${plural(age, 'day')} ago` : ''} and are awaiting a reply.`)
  else if (status === 'added') out.push('It is queued and ready to apply.')
  else if (status === 'dismissed') out.push(`You dismissed it${job.decision_notes ? `: ${job.decision_notes}` : '.'}`)
  else if (age != null && age > 7) out.push(`It has sat in the pipeline for ${plural(age, 'day')} without an application.`)

  const others = co.jobs.filter((j) => j.id !== job.id)
  if (others.length) out.push(`${job.company} has ${plural(others.length, 'other opening')} in your pipeline.`)
  if (co.interviews.length) out.push(`You have already interviewed with ${job.company} ${plural(co.interviews.length, 'time')}.`)
  if (co.people.length) out.push(`You know ${plural(co.people.length, 'contact')} there — warm intros beat cold applications.`)
  else if (status !== 'applied' && status !== 'dismissed') out.push('No contacts at this company yet — finding one before applying would strengthen your odds.')

  return out.slice(0, 5)
}

export function interviewSummary(iv: Interview, ds: Datasets): string[] {
  const out: string[] = []
  const co = iv.company ? companyBundle(ds, iv.company) : null
  const days = daysSince(iv.interview_date)
  const type = (iv.interview_type || 'interview').replace(/_/g, ' ')

  if (iv.upcoming) {
    if (days != null && days <= 0) {
      out.push(days === 0 ? `Your ${type} at ${iv.company} is today.` : `Your ${type} at ${iv.company} is in ${plural(-days, 'day')}.`)
    } else out.push(`Upcoming ${type} at ${iv.company}.`)
    if (iv.interviewer) out.push(`You will meet ${iv.interviewer}${iv.interviewer_role ? `, ${iv.interviewer_role}` : ''}.`)
    const past = (co?.interviews || []).filter((i) => !i.upcoming)
    if (past.length) out.push(`You have ${plural(past.length, 'previous debrief')} with this company — review them before the call.`)
    else out.push('First conversation with this company — research their interview process beforehand.')
  } else {
    if (iv.self_rating != null) {
      if (iv.self_rating >= 8) out.push(`Strong performance — you rated it ${iv.self_rating}/10.`)
      else if (iv.self_rating >= 6) out.push(`Decent showing at ${iv.self_rating}/10 with clear room to improve.`)
      else out.push(`Tough one — you rated it ${iv.self_rating}/10.`)
    } else out.push(`Debrief logged for this ${type} at ${iv.company}.`)
    if (iv.what_landed?.length) out.push(`What landed: ${iv.what_landed[0]}`)
    if (iv.what_didnt?.length) out.push(`Weak spot to drill: ${iv.what_didnt[0]}`)
    const q = quoteText(iv.verbatim_quotes?.[0])
    if (q) out.push(`Worth remembering — “${q}”`)
  }
  return out.slice(0, 5)
}

export function personSummary(p: Person, ds: Datasets): string[] {
  const out: string[] = []
  const co = p.company ? companyBundle(ds, p.company) : null
  const status = (p.outreach_status || '').toLowerCase()
  const gap = daysSince(p.last_contacted || p.last_updated)

  out.push(
    `${p.name} is ${p.relationship ? `a ${p.relationship}` : 'a contact'}${p.company ? ` at ${p.company}` : ''}.`,
  )
  if (status === 'responded') out.push('They replied to your last outreach — the ball is in your court.')
  else if (status === 'sent') out.push('Your last message is awaiting a reply.')
  else if (status === 'follow-up') out.push('A follow-up is due.')
  else if (status === 'drafted') out.push('You drafted outreach but have not sent it yet.')
  else out.push('You have not reached out yet.')

  if (gap != null && gap > 14) out.push(`No contact in ${plural(gap, 'day')} — the relationship is going cold.`)
  else if (gap != null && gap >= 0) out.push(`Last touch was ${gap === 0 ? 'today' : `${plural(gap, 'day')} ago`}.`)

  if (co) {
    const active = co.jobs.filter((j) => !['dismissed'].includes((j.status || '').toLowerCase()))
    if (active.length) out.push(`${p.company} has ${plural(active.length, 'live opening')} in your pipeline — a concrete reason to reconnect.`)
    if (co.interviews.length) out.push(`You have interviewed there ${plural(co.interviews.length, 'time')}.`)
  }
  const { email, phone, linkedin } = contactChannels(p)
  if (!email && !phone && !linkedin) out.push('No contact channel on file — add an email or LinkedIn from the desktop.')
  return out.slice(0, 5)
}

export function companySummary(co: CompanyBundle): string[] {
  const out: string[] = []
  const active = co.jobs.filter((j) => (j.status || '').toLowerCase() !== 'dismissed')
  const applied = co.jobs.filter((j) => (j.status || '').toLowerCase() === 'applied')
  const scores = co.jobs.map((j) => Number(j.fitment_score) || 0).filter((s) => s > 0)
  const best = scores.length ? Math.max(...scores) : 0

  out.push(
    `${co.name} touches ${plural(co.jobs.length, 'job')}, ${plural(co.interviews.length, 'interview')}, and ${plural(co.people.length, 'contact')} in your search.`,
  )
  if (applied.length) out.push(`${plural(applied.length, 'application')} in flight.`)
  if (best >= 85) out.push(`Your best fit there scores ${best} — one of your strongest matches.`)
  else if (best > 0) out.push(`Best fit score there is ${best}.`)
  const upcoming = co.interviews.filter((i) => i.upcoming)
  if (upcoming.length) out.push(`${plural(upcoming.length, 'interview')} coming up — prep time is now.`)
  else if (co.interviews.length) out.push(`You have completed ${plural(co.interviews.length, 'interview')} with them — the debriefs hold their question style.`)
  if (!co.people.length && active.length) out.push('No contacts here yet — networking in would derisk the applications.')
  return out.slice(0, 5)
}

export function postSummary(post: Post, ds: Datasets): string[] {
  const out: string[] = []
  const n = ds.posts.length || 1
  const avgImp = ds.postTotals.impressions / n
  const avgRx = ds.postTotals.reactions / n
  const rate = post.impressions > 0 ? ((post.reactions + post.comments) / post.impressions) * 100 : 0

  if (post.impressions === 0 && post.reactions === 0) {
    out.push('No metrics logged yet — update them from LinkedIn to see how this post performed.')
  } else {
    if (avgImp > 0 && post.impressions >= avgImp * 1.5) out.push(`Top performer — ${Math.round((post.impressions / avgImp) * 100 - 100)}% more impressions than your average post.`)
    else if (avgImp > 0 && post.impressions < avgImp * 0.5) out.push('This one reached well under your average — timing or topic may not have landed.')
    else out.push('Reach was in line with your usual audience.')
    if (rate > 0) out.push(`Engagement rate ${rate.toFixed(1)}% (${post.reactions} reactions, ${post.comments} comments).`)
    if (avgRx > 0 && post.reactions > avgRx * 1.5) out.push('Reactions ran hot — this topic resonates; consider a follow-up post.')
  }
  if (post.hashtags?.length) out.push(`Tagged ${post.hashtags.slice(0, 3).map((h) => (h.startsWith('#') ? h : `#${h}`)).join(' ')}.`)
  const age = daysSince(post.posted_date)
  if (age != null && age >= 0) out.push(`Published ${age === 0 ? 'today' : `${plural(age, 'day')} ago`}.`)
  return out.slice(0, 5)
}

export function checkinSummary(entry: Checkin, ds: Datasets): string[] {
  const out: string[] = []
  const energies = ds.checkins.map((c) => c.energy || 0).filter((e) => e > 0)
  const avg = energies.length ? energies.reduce((a, b) => a + b, 0) / energies.length : 0

  if (entry.mood) out.push(`You logged feeling ${entry.mood}.`)
  if (typeof entry.energy === 'number') {
    if (avg > 0 && entry.energy >= avg + 1.5) out.push(`Energy ${entry.energy}/10 — well above your ${avg.toFixed(1)} average. Days like this are for outreach and interviews.`)
    else if (avg > 0 && entry.energy <= avg - 1.5) out.push(`Energy ${entry.energy}/10 — below your ${avg.toFixed(1)} average. Keep the load light.`)
    else out.push(`Energy ${entry.energy}/10, close to your recent average.`)
  }
  out.push(entry.productive ? 'You marked it a productive day.' : 'Not marked productive — that is signal, not failure.')
  if (entry.notes) out.push('Your journal entry below has the context.')
  return out.slice(0, 5)
}

/** Cross-cutting observations for search/timeline empty moments and the
 *  company screen footer — "surface observations, not just data". */
export function globalInsights(ds: Datasets): string[] {
  const out: string[] = []
  const stale = ds.people.filter((p) => {
    const s = (p.outreach_status || '').toLowerCase()
    const gap = daysSince(p.last_contacted || p.last_updated)
    return ['sent', 'responded', 'follow-up'].includes(s) && gap != null && gap > 14
  })
  if (stale.length) out.push(`${plural(stale.length, 'conversation')} have gone quiet for 2+ weeks.`)
  const unassessed = ds.jobs.filter((j) => !j.assessed && (j.status || 'pending') === 'pending')
  if (unassessed.length) out.push(`${plural(unassessed.length, 'captured job')} still await assessment.`)
  const counts = new Map<string, number>()
  ds.interviews.forEach((i) => {
    const k = normName(i.company)
    if (k) counts.set(k, (counts.get(k) || 0) + 1)
  })
  for (const [key, count] of counts) {
    if (count >= 3) {
      const name = ds.interviews.find((i) => normName(i.company) === key)?.company
      out.push(`You have interviewed at ${name} ${count} times.`)
      break
    }
  }
  return out
}
