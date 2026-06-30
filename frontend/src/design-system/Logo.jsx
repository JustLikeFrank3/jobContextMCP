/* Logo — the jobContext brand mark (j + cyan C) with optional wordmark.
   Geometry matches docs/branding/logo/jobcontextmcp-mark-dark.svg exactly.

   Props:
     size          number  — pixel height of the mark (default 32)
     markOnly      bool    — render just the mark, no "jobContext" wordmark
     wordmarkOnly  bool    — render just the "jobContext" wordmark, no mark
*/
export default function Logo({ size = 32, markOnly = false, wordmarkOnly = false }) {
  const mark = (
    <svg
      width={size}
      height={size}
      viewBox="0 0 320 320"
      role="img"
      aria-label="jobContext"
      style={{ display: 'block', flexShrink: 0 }}
    >
      <title>jobContext</title>
      {/* framed badge: dark disc + cyan ring */}
      <circle cx="160" cy="160" r="153" fill="var(--ink-900)" />
      <circle cx="160" cy="160" r="153" fill="none" stroke="var(--cyan-500)" strokeWidth="10" />
      <g transform="translate(-12 0)">
        {/* C: cyan arc */}
        <path
          d="M234 118 A56 56 0 1 0 234 202"
          fill="none"
          stroke="var(--cyan-500)"
          strokeWidth="32"
          strokeLinecap="round"
        />
        {/* j: dot + stem + hook */}
        <circle cx="100" cy="112" r="19" fill="var(--text-strong)" />
        <path
          d="M100 142 L100 205 Q100 230 74 230"
          fill="none"
          stroke="var(--text-strong)"
          strokeWidth="30"
          strokeLinecap="round"
        />
      </g>
    </svg>
  )

  if (markOnly) return mark

  const wordmark = (
    <span
      style={{
        fontFamily: 'var(--font-display)',
        fontWeight: 'var(--fw-bold)',
        fontSize: `${size * 0.62}px`,
        letterSpacing: '-0.01em',
        lineHeight: 1,
      }}
    >
      <span style={{ color: 'var(--text-strong)' }}>job</span>
      <span style={{ color: 'var(--cyan-400)' }}>Context</span>
    </span>
  )

  if (wordmarkOnly) return wordmark

  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 10 }}>
      {mark}
      {wordmark}
    </span>
  )
}
