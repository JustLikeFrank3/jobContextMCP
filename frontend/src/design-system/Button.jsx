import { useState } from 'react'

/* Button — design-system button primitive.

   Props:
     variant  'primary' | 'ghost'  (default 'primary')
     size     'sm' | 'md'          (default 'md')
     onClick, type, disabled, children, ...rest
*/
export default function Button({
  variant = 'primary',
  size = 'md',
  onClick,
  type = 'button',
  disabled = false,
  children,
  ...rest
}) {
  const [hover, setHover] = useState(false)

  const pad = size === 'sm' ? '7px 13px' : '9px 18px'
  const fs = size === 'sm' ? 'var(--fs-sm)' : 'var(--fs-base)'

  const base = {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 7,
    padding: pad,
    fontFamily: 'var(--font-sans)',
    fontWeight: 'var(--fw-medium)',
    fontSize: fs,
    lineHeight: 1,
    borderRadius: 'var(--radius-sm)',
    cursor: disabled ? 'not-allowed' : 'pointer',
    opacity: disabled ? 0.5 : 1,
    transition:
      'background var(--dur-base), color var(--dur-base), border-color var(--dur-base)',
  }

  const variants = {
    primary: {
      background: hover
        ? 'color-mix(in srgb, var(--cyan-500) 88%, white)'
        : 'var(--cyan-500)',
      color: '#04222a',
      border: '1px solid transparent',
      fontWeight: 'var(--fw-semibold)',
    },
    ghost: {
      background: 'transparent',
      color: hover ? 'var(--text)' : 'var(--muted)',
      border: `1px solid ${hover ? 'var(--line-strong)' : 'var(--border)'}`,
    },
  }

  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{ ...base, ...variants[variant] }}
      {...rest}
    >
      {children}
    </button>
  )
}
