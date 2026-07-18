import { useEffect, useState } from 'react'
import { useNavigate, useLocation, Outlet } from 'react-router-dom'
import { Logo, NavTabs, Button, Icon } from '../design-system'
import useDesktopMode from './useDesktopMode.js'
import Sidebar from './Sidebar.jsx'
import { ToolbarSlotContext } from './toolbarSlot.jsx'

/* DashboardShell — app chrome per the desktop design handoff: a 236px
   sidebar (WORKSPACE nav + TOOLS + pinned Settings + status card) beside a
   scrollable main column with a sticky toolbar (breadcrumb left, per-screen
   slot right — screens project actions/steps via useToolbarSlot). The page
   title renders at the top of the content column, design-style.

   Narrow viewports (<880px) fall back to the previous header + NavTabs
   layout via the .jc-* classes in global.css — the sidebar design targets
   desktop-width windows. */

const PRIMARY_NAV = [
  { label: 'Home', key: 'home' },
  { label: 'Pipeline', key: 'pipeline' },
  { label: 'Interviews', key: 'interviews' },
  { label: 'People', key: 'people' },
  { label: 'Posts', key: 'posts' },
  { label: 'Wellbeing', key: 'health' },
]

const SECONDARY_NAV = [
  { label: 'Job Hunt', key: 'job-hunt' },
  { label: 'Materials', key: 'materials' },
  { label: 'Rejections', key: 'rejections' },
  { label: 'API Keys', key: 'api-keys' },
]

const CHAT_ITEM = { label: 'Chat', key: 'chat' }

const PAGE_META = {
  home: ['Home', 'Your career command center'],
  pipeline: [
    'Pipeline',
    'Share-sheet intake → assessment → resume → cover letter → queue apply',
  ],
  'job-hunt': ['Job Hunt Tracker', 'Applications & Kanban board'],
  materials: ['Materials', 'Resumes, cover letters, PDFs, and untracked files'],
  rejections: ['Rejections', 'Funnel analysis & patterns'],
  posts: ['Posts', 'LinkedIn pipeline: draft → written → approved → posted'],
  people: ['People', 'Contacts, follow-up queue, warm vs cold'],
  health: ['Wellbeing', 'Mood & energy log, trend sparklines'],
  interviews: ['Interviews', 'Upcoming schedule, debrief log, verbatim quotes'],
  chat: ['Chat', 'Ask about your job search — answers come from your local data'],
  settings: ['Settings', 'API keys, integrations (Oura ring) & account preferences'],
  'api-keys': ['API Keys', 'Personal access tokens for MCP clients'],
}

const keyToPath = (key) => (key === 'home' ? '/' : `/${key}`)
const pathToKey = (pathname) => {
  const seg = pathname.replace(/^\/+/, '').split('/')[0]
  return seg || 'home'
}

// Single source of truth for the narrow/wide split so only ONE layout (and
// one <Outlet/>) mounts — rendering both would double-mount every screen.
function useNarrowViewport() {
  const [narrow, setNarrow] = useState(() => window.matchMedia('(max-width: 880px)').matches)
  useEffect(() => {
    const mq = window.matchMedia('(max-width: 880px)')
    const onChange = (e) => setNarrow(e.matches)
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [])
  return narrow
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
  const narrow = useNarrowViewport()
  const [slotNode, setSlotNode] = useState(null)

  const secondary = isDesktop ? [...SECONDARY_NAV.slice(0, 3), CHAT_ITEM, SECONDARY_NAV[3]] : SECONDARY_NAV
  const allItems = [...PRIMARY_NAV, ...secondary, { label: 'Settings', key: 'settings' }]
  const tab = pathToKey(location.pathname)
  const [title, subtitle] = PAGE_META[tab] || [allItems.find((t) => t.key === tab)?.label || '', '']
  const go = (key) => navigate(keyToPath(key))

  if (narrow) {
    return (
      <ToolbarSlotContext.Provider value={{ node: slotNode, setNode: setSlotNode }}>
        <div className="jc-narrow">
          <header
            style={{
              display: 'flex', justifyContent: 'space-between', alignItems: 'center',
              gap: 16, marginBottom: 18, flexWrap: 'wrap',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 14, minWidth: 0 }}>
              <Logo size={36} markOnly />
              <div>
                <h1 style={{ margin: 0, font: 'var(--text-page-title)', color: 'var(--text-strong)' }}>
                  {title || <Logo size={26} wordmarkOnly />}
                </h1>
                {subtitle && (
                  <div style={{ color: 'var(--muted)', fontSize: 'var(--fs-sm)', marginTop: 4 }}>{subtitle}</div>
                )}
              </div>
            </div>
            {!isDesktop && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <Button variant="ghost" size="sm" onClick={() => navigate('/settings')}>
                  <span style={{ display: 'inline-flex', color: 'var(--muted)' }}>
                    <Icon name="settings" size={15} />
                  </span>
                  Settings
                </Button>
                <Button variant="ghost" size="sm" onClick={signOut}>Sign out</Button>
              </div>
            )}
          </header>
          <div style={{ marginBottom: 12 }}>
            <NavTabs items={allItems} active={tab} onSelect={go} />
          </div>
          {slotNode && (
            <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 12 }}>{slotNode}</div>
          )}
          <Outlet />
        </div>
      </ToolbarSlotContext.Provider>
    )
  }

  return (
    <ToolbarSlotContext.Provider value={{ node: slotNode, setNode: setSlotNode }}>
      <div className="jc-shell">
        <Sidebar
          primary={PRIMARY_NAV}
          secondary={secondary}
          active={tab}
          onSelect={go}
          isDesktop={isDesktop}
          onSignOut={signOut}
        />

        <div className="jc-main jc-scroll">
          <div className="jc-toolbar">
            <div style={{ fontSize: 13, color: '#7C8AA6', fontWeight: 'var(--fw-medium)' }}>{title}</div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              {slotNode}
              {!isDesktop && !slotNode && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => window.open('/why', '_blank', 'noopener,noreferrer')}
                >
                  Why use jobContext?
                </Button>
              )}
            </div>
          </div>

          <div className="jc-page">
            <h1 style={{ margin: 0, fontFamily: 'var(--font-display)', fontSize: 28, fontWeight: 'var(--fw-bold)', letterSpacing: '-0.6px', color: 'var(--text)' }}>
              {title || <Logo size={26} wordmarkOnly />}
            </h1>
            {subtitle && (
              <div style={{ color: 'var(--muted)', fontSize: 'var(--fs-sm)', marginTop: 4, marginBottom: 4 }}>{subtitle}</div>
            )}
            <div style={{ marginTop: 18 }}>
              <Outlet />
            </div>
          </div>
        </div>
      </div>
    </ToolbarSlotContext.Provider>
  )
}

export { PRIMARY_NAV, SECONDARY_NAV, PAGE_META }
