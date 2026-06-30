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
      viewBox="0 0 100 100"
      role="img"
      aria-label="jobContext"
      style={{ display: 'block', flexShrink: 0 }}
    >
      <title>jobContext</title>
      {/* j: dot + stem + hook */}
      <circle cx="27" cy="21" r="7" fill="var(--text-strong)" />
      <path
        d="M27 31 L27 61 Q27 73 16 73"
        fill="none"
        stroke="var(--text-strong)"
        strokeWidth="9"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      {/* C: cyan arc */}
      <path
        d="M77 27 A24 24 0 1 0 77 67"
        fill="none"
        stroke="var(--cyan-500)"
        strokeWidth="9"
        strokeLinecap="round"
      />
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
