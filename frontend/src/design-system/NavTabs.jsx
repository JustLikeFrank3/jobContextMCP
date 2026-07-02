import { useState } from 'react'

/* NavTabs — horizontal tab bar with active highlight + hover.

   Props:
     items     [{ label, key }]
     active    string  — active key
     onSelect  (key) => void
*/
function Tab({ item, active, onSelect }) {
  const [hover, setHover] = useState(false)
  const on = active === item.key

  return (
    <button
      type="button"
      onClick={() => onSelect(item.key)}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        appearance: 'none',
        background: on ? 'var(--surface-raised)' : 'transparent',
        border: '1px solid',
        borderColor: on
          ? 'color-mix(in srgb, var(--cyan-500) 40%, transparent)'
          : hover
            ? 'var(--border)'
            : 'transparent',
        color: on ? 'var(--text-strong)' : hover ? 'var(--text)' : 'var(--muted)',
        fontFamily: 'var(--font-sans)',
        fontSize: 'var(--fs-sm)',
        fontWeight: on ? 'var(--fw-semibold)' : 'var(--fw-medium)',
        padding: '7px 14px',
        borderRadius: 'var(--radius-sm)',
        cursor: 'pointer',
        whiteSpace: 'nowrap',
        transition:
          'background var(--dur-base), color var(--dur-base), border-color var(--dur-base)',
      }}
    >
      {item.label}
    </button>
  )
}

export default function NavTabs({ items, active, onSelect }) {
  return (
    <nav
      style={{
        display: 'flex',
        flexWrap: 'wrap',
        gap: 4,
        padding: 4,
        background: 'var(--surface)',
        border: '1px solid var(--border)',
        borderRadius: 'var(--radius-md)',
      }}
    >
      {items.map((item) => (
        <Tab key={item.key} item={item} active={active} onSelect={onSelect} />
      ))}
    </nav>
  )
}
