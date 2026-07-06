import { useNavigate, useLocation, Outlet } from 'react-router-dom'
import { Logo, NavTabs, Button, Icon } from '../design-system'
import useDesktopMode from './useDesktopMode.js'

/* DashboardShell — app chrome: header (logo + title + settings gear + sign
   out) and the tab bar. Converted from the design handoff's shell.jsx IIFE to
   ESM and wired to react-router so each tab is a real URL.

   Deltas from the original kit shell (per handoff):
   - Digest tab removed (its content now lives on Home as the Oura fallback)
   - Settings reached via the header button (no nav tab)
   - API Keys kept as its own tab
*/

const TABS = [
  { label: 'Home', key: 'home' },
  { label: 'Pipeline', key: 'pipeline' },
  { label: 'Job Hunt', key: 'job-hunt' },
  { label: 'Materials', key: 'materials' },
  { label: 'Rejections', key: 'rejections' },
  { label: 'Posts', key: 'posts' },
  { label: 'Outreach', key: 'people' },
  { label: 'Wellbeing', key: 'health' },
  { label: 'Interviews', key: 'interviews' },
  { label: 'API Keys', key: 'api-keys' },
]

// Desktop-only tab, spliced in before API Keys when the backend is the
// desktop app (useDesktopMode probe) — hosted deployments never show it.
const CHAT_TAB = { label: 'Chat', key: 'chat' }

const PAGE_META = {
  home: ['', 'Your career command center'],
  pipeline: [
    'Pipeline',
    'Share-sheet intake \u2192 assessment \u2192 resume \u2192 cover letter \u2192 queue apply',
  ],
  'job-hunt': ['Job Hunt Tracker', 'Applications & Kanban board'],
  materials: ['Materials', 'Resumes, cover letters, PDFs, and untracked files'],
  rejections: ['Rejections', 'Funnel analysis & patterns'],
  posts: ['Posts', 'LinkedIn pipeline: draft \u2192 written \u2192 approved \u2192 posted'],
  people: ['Outreach', 'Contacts, follow-up queue, warm vs cold'],
  health: ['Wellbeing', 'Mood & energy log, trend sparklines'],
  interviews: ['Interviews', 'Upcoming schedule, debrief log, verbatim quotes'],
  chat: ['Chat', 'Ask about your job search — answers come from your local data'],
  settings: ['Settings', 'API keys, integrations (Oura ring) & account preferences'],
  'api-keys': ['API Keys', 'Personal access tokens for MCP clients'],
}

// Map a tab key to its client route and back.
const keyToPath = (key) => (key === 'home' ? '/' : `/${key}`)
const pathToKey = (pathname) => {
  const seg = pathname.replace(/^\/+/, '').split('/')[0]
  return seg || 'home'
}

// Sign out is a server-side POST /logout (clears the cookie + redirects).
function signOut() {
  const form = document.createElement('form')
  form.method = 'POST'
  form.action = '/logout'
  document.body.appendChild(form)
  form.submit()
}

export default function DashboardShell() {
  const navigate = useNavigate()
  const location = useLocation()
  const isDesktop = useDesktopMode()
  const tabs = isDesktop
    ? [...TABS.slice(0, -1), CHAT_TAB, TABS[TABS.length - 1]]
    : TABS
  const tab = pathToKey(location.pathname)
  const [title, subtitle] = PAGE_META[tab] || [
    tabs.find((t) => t.key === tab)?.label || '',
    '',
  ]

  return (
    <div
      style={{
        maxWidth: 'var(--wrap-max)',
        margin: '0 auto',
        padding: 'var(--page-pad)',
      }}
    >
      <header
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          gap: 16,
          marginBottom: 18,
          flexWrap: 'wrap',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 14, minWidth: 0 }}>
          <Logo size={36} markOnly />
          <div>
            <h1 style={{ margin: 0, font: 'var(--text-page-title)', color: 'var(--text-strong)' }}>
              {title || <Logo size={26} wordmarkOnly />}
            </h1>
            {subtitle && (
              <div style={{ color: 'var(--muted)', fontSize: 'var(--fs-sm)', marginTop: 4 }}>
                {subtitle}
              </div>
            )}
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => window.open('/why', '_blank', 'noopener,noreferrer')}
          >
            <span style={{ display: 'inline-flex', color: 'var(--muted)' }}>
              <svg viewBox="0 0 20 20" width={15} height={15} fill="none" stroke="currentColor" strokeWidth={1.5}>
                <circle cx="10" cy="10" r="7.5" />
                <path d="M10 9v4.5" strokeLinecap="round" />
                <circle cx="10" cy="6.5" r="0.8" fill="currentColor" stroke="none" />
              </svg>
            </span>
            Why use jobContext?
          </Button>
          <Button variant="ghost" size="sm" onClick={() => navigate('/settings')}>
            <span style={{ display: 'inline-flex', color: 'var(--muted)' }}>
              <Icon name="settings" size={15} />
            </span>
            Settings
          </Button>
          <Button variant="ghost" size="sm" onClick={signOut}>
            Sign out
          </Button>
        </div>
      </header>

      <div style={{ marginBottom: 22 }}>
        <NavTabs
          items={tabs}
          active={tab}
          onSelect={(key) => navigate(keyToPath(key))}
        />
      </div>

      <Outlet />
    </div>
  )
}

export { TABS, PAGE_META }
