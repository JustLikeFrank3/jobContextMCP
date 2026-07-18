import Logo from '../design-system/Logo.jsx'

/* Sidebar — the desktop design's left rail: badge + wordmark, WORKSPACE nav
   with gradient-glass active pills and a cyan left accent bar, secondary
   TOOLS section (routes the design bundle doesn't cover but the product
   has), Settings pinned to the bottom, and the workspace status card
   (LOCAL · SQLITE on desktop, CLOUD WORKSPACE hosted). */

const STROKE = { fill: 'none', stroke: 'currentColor', strokeWidth: 1.7, strokeLinecap: 'round', strokeLinejoin: 'round' }

const ICONS = {
  home: <g><path d="M4 11 L12 4 L20 11" /><path d="M6 10 V19 H18 V10" /></g>,
  pipeline: <g><circle cx="5" cy="6" r="1.4" /><path d="M9 6h11" /><circle cx="5" cy="12" r="1.4" /><path d="M9 12h11" /><circle cx="5" cy="18" r="1.4" /><path d="M9 18h11" /></g>,
  interviews: <g><rect x="4" y="5" width="16" height="15" rx="2.5" /><path d="M4 9 H20 M9 3 V7 M15 3 V7" /></g>,
  people: <g><circle cx="9" cy="8" r="3" /><path d="M4 19c0-3 2.3-5 5-5s5 2 5 5" /><circle cx="16.5" cy="9" r="2.2" /><path d="M15 14.2c2.2.2 4 2 4 4.8" /></g>,
  posts: <g><circle cx="12" cy="12" r="2.2" /><path d="M8.5 8.5a5 5 0 0 0 0 7 M15.5 8.5a5 5 0 0 1 0 7 M6 6a9 9 0 0 0 0 12 M18 6a9 9 0 0 1 0 12" /></g>,
  health: <path d="M12 20s-7-4.6-7-9.6A3.9 3.9 0 0 1 12 8 A3.9 3.9 0 0 1 19 10.4C19 15.4 12 20 12 20Z" />,
  settings: <g><path d="M4 7h7 M17 7h3 M4 12h3 M11 12h9 M4 17h11 M19 17h1" /><circle cx="14" cy="7" r="2.2" /><circle cx="7" cy="12" r="2.2" /><circle cx="16" cy="17" r="2.2" /></g>,
  'job-hunt': <g><rect x="4" y="5" width="4.5" height="14" rx="1.4" /><rect x="10" y="5" width="4.5" height="9" rx="1.4" /><rect x="16" y="5" width="4.5" height="12" rx="1.4" /></g>,
  materials: <path d="M3.5 7.5a2 2 0 0 1 2-2h4l2 2.5h7a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2Z" />,
  rejections: <g><circle cx="12" cy="12" r="8" /><path d="M9.5 9.5l5 5 M14.5 9.5l-5 5" /></g>,
  chat: <path d="M4 6.5A2.5 2.5 0 0 1 6.5 4h11A2.5 2.5 0 0 1 20 6.5v8a2.5 2.5 0 0 1-2.5 2.5H9l-5 4Z" />,
  'api-keys': <g><circle cx="8" cy="14" r="4" /><path d="M11 11 L20 4 M16 7l2.5 2.5 M13 10l2 2" /></g>,
}

function NavIcon({ name }) {
  return (
    <svg width={19} height={19} viewBox="0 0 24 24" {...STROKE} style={{ flexShrink: 0 }}>
      {ICONS[name] || ICONS.home}
    </svg>
  )
}

function NavItem({ item, active, onSelect }) {
  return (
    <div
      onClick={() => onSelect(item.key)}
      style={{
        position: 'relative', display: 'flex', alignItems: 'center', gap: 11,
        padding: '9px 12px', borderRadius: 10, cursor: 'pointer',
        fontSize: '13.5px', fontWeight: 'var(--fw-medium)',
        background: active ? 'linear-gradient(90deg, rgba(0,181,200,.2), rgba(0,181,200,.04))' : 'transparent',
        color: active ? 'var(--cyan-300)' : '#93A2BE',
        boxShadow: active ? 'inset 0 0 0 1px rgba(0,181,200,.22), 0 0 18px rgba(0,181,200,.1)' : 'none',
      }}
    >
      <div style={{ position: 'absolute', left: 0, top: 8, bottom: 8, width: 3, borderRadius: 3, background: active ? 'var(--cyan-500)' : 'transparent' }} />
      <NavIcon name={item.key} />
      {item.label}
    </div>
  )
}

const MONO_HEAD = {
  fontSize: 10, fontWeight: 'var(--fw-semibold)', letterSpacing: 1.5,
  color: '#56637E', fontFamily: 'var(--font-mono)', padding: '4px 10px 8px',
}

export default function Sidebar({ primary, secondary, active, onSelect, isDesktop, onSignOut }) {
  return (
    <div className="jc-sidebar jc-scroll">
      <div style={{ display: 'flex', alignItems: 'center', gap: 11, padding: '2px 8px 20px' }}>
        <span style={{ filter: 'drop-shadow(0 0 12px rgba(0,181,200,.4))' }}><Logo size={34} markOnly /></span>
        <div>
          <div style={{ fontSize: 15, fontWeight: 'var(--fw-bold)', color: 'var(--text)', lineHeight: 1 }}>jobContext</div>
          <div style={{ fontSize: 10, fontWeight: 'var(--fw-medium)', color: '#6B7A96', fontFamily: 'var(--font-mono)', letterSpacing: 1, marginTop: 3 }}>
            {isDesktop ? 'DESKTOP' : 'CLOUD'}
          </div>
        </div>
      </div>

      <div style={MONO_HEAD}>WORKSPACE</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
        {primary.map((item) => (
          <NavItem key={item.key} item={item} active={active === item.key} onSelect={onSelect} />
        ))}
      </div>

      <div style={{ ...MONO_HEAD, paddingTop: 18 }}>TOOLS</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
        {secondary.map((item) => (
          <NavItem key={item.key} item={item} active={active === item.key} onSelect={onSelect} />
        ))}
      </div>

      <div style={{ flex: 1, minHeight: 18 }} />

      <NavItem item={{ key: 'settings', label: 'Settings' }} active={active === 'settings'} onSelect={onSelect} />

      <div style={{ marginTop: 10, padding: 12, borderRadius: 12, background: 'rgba(0,181,200,.06)', border: '1px solid rgba(0,181,200,.14)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <div style={{ width: 7, height: 7, borderRadius: '50%', background: '#6FD3A0', animation: 'jc-pulse 2s ease-in-out infinite' }} />
          <span style={{ fontSize: 11, fontWeight: 'var(--fw-semibold)', color: '#8FD3AE', fontFamily: 'var(--font-mono)' }}>
            {isDesktop ? 'LOCAL · SQLITE' : 'CLOUD WORKSPACE'}
          </span>
        </div>
        <div style={{ fontSize: 11, color: '#7C93A8', lineHeight: 1.45, marginTop: 6 }}>
          {isDesktop
            ? 'All data stays on this machine. Nothing leaves the device.'
            : 'Synced workspace — desktop and mobile stay up to date.'}
        </div>
        {!isDesktop && (
          <div onClick={onSignOut} style={{ marginTop: 8, fontSize: 11.5, fontWeight: 'var(--fw-semibold)', color: 'var(--cyan-300)', cursor: 'pointer' }}>
            Sign out
          </div>
        )}
      </div>
    </div>
  )
}
