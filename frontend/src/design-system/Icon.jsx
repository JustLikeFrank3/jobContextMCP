/* Icon — the jobContext line-icon set (1.5 stroke, currentColor).
   Ported from the design handoff's JCICON map. Color is inherited via
   currentColor so callers set color on the wrapper.

   Props:
     name  string  — one of the keys below
     size  number  — pixel size (default 22)
*/
const PATHS = {
  pipeline: <path d="M3 5h14M3 10h10M3 15h6" />,
  'job-hunt': (
    <g>
      <rect x="3" y="3" width="14" height="14" rx="2" />
      <path d="M7 7h6M7 10h6M7 13h4" />
    </g>
  ),
  materials: (
    <g>
      <path d="M4 4h8l4 4v8a1 1 0 01-1 1H4a1 1 0 01-1-1V5a1 1 0 011-1z" />
      <path d="M12 4v4h4" />
    </g>
  ),
  rejections: (
    <g>
      <circle cx="10" cy="10" r="7" />
      <path d="M10 6v4l3 3" />
    </g>
  ),
  posts: <path d="M2 13l4-4 3 3 4-5 5 6" />,
  people: (
    <g>
      <circle cx="8" cy="7" r="3" />
      <path d="M2 17c0-3 2.5-5 6-5s6 2 6 5" />
      <circle cx="15" cy="7" r="2" />
      <path d="M15 12c2 .5 3 2 3 4" />
    </g>
  ),
  health: (
    <g>
      <path d="M3 14l3-4 3 2 3-5 3 3" />
      <path d="M3 17h14" />
    </g>
  ),
  interviews: (
    <g>
      <circle cx="10" cy="8" r="4" />
      <path d="M3 17c0-3 3-5 7-5s7 2 7 5" />
    </g>
  ),
  settings: (
    <g>
      <circle cx="10" cy="10" r="2.6" />
      <path d="M10 1.8v2M10 16.2v2M3.2 10h-2M18.8 10h-2M5.2 5.2 3.8 3.8M16.2 16.2l-1.4-1.4M14.8 5.2l1.4-1.4M3.8 16.2l1.4-1.4" />
    </g>
  ),
  'api-keys': (
    <g>
      <circle cx="7" cy="10" r="3.5" />
      <path d="M10.5 10H18M15 10v3M18 10v2.5" />
    </g>
  ),
}

export default function Icon({ name, size = 22 }) {
  return (
    <svg
      viewBox="0 0 20 20"
      width={size}
      height={size}
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {PATHS[name] || null}
    </svg>
  )
}
