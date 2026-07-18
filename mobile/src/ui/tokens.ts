// Design tokens from the jobContext design handoff (README "Design Tokens").
// Navy-ink background, cyan accent, mono micro-labels.
import { Platform } from 'react-native'

export const t = {
  // Backgrounds. The design is a 165° gradient #0A0F1C → #0B1220; without
  // expo-linear-gradient we use the midpoint as a solid base (the two ends
  // are nearly indistinguishable at phone size).
  bg: '#0A0F1C',
  bgEnd: '#0B1220',
  sheet: '#0E1524',

  // Accent
  cyan: '#00B5C8',
  cyanBright: '#6FE0EE',
  cyanInk: '#04222A', // text on cyan buttons

  // Text
  text: '#F0F5FF',
  textBright: '#E8EFFB',
  textBody: '#C9D6EC',
  textSoft: '#B7C6E0',
  textSecondary: '#A9B6CE',
  muted: '#8A99B5',
  muted2: '#7C8AA6',
  faint: '#6B7A96',
  cyanMuted: '#8AB6C4',

  // Status
  green: '#6FD3A0',
  amber: '#E0B77A',
  red: '#E39393',

  // Surfaces
  card: 'rgba(255,255,255,.04)',
  cardRaised: 'rgba(255,255,255,.045)',
  cardBorder: 'rgba(255,255,255,.07)',
  cardBorderRaised: 'rgba(255,255,255,.08)',
  chipBg: 'rgba(255,255,255,.05)',
  hairline: 'rgba(255,255,255,.06)',

  // Cyan tints
  tintFillLo: 'rgba(0,181,200,.06)',
  tintFill: 'rgba(0,181,200,.10)',
  tintFillHi: 'rgba(0,181,200,.16)',
  tintBorderLo: 'rgba(0,181,200,.16)',
  tintBorder: 'rgba(0,181,200,.24)',
  tintBorderHi: 'rgba(0,181,200,.28)',

  // Tab bar
  tabBg: 'rgba(10,15,28,.96)',
  tabInactive: 'rgba(215,227,248,.45)',
}

// TODO(fonts): the design specifies Space Grotesk (display) + JetBrains Mono
// (labels). The app does not currently load custom fonts (no expo-font /
// @expo-google-fonts dependency), so we fall back to the system stack and
// the platform monospace face until the fonts are added.
export const fonts = {
  display: undefined as string | undefined, // system default
  mono: Platform.select({ ios: 'Menlo', android: 'monospace', default: 'monospace' }),
}

// Pipeline stage chip palette (design: Offer green, Onsite cyan, Screen
// amber, Applied/Interested neutral), mapped onto the server's real status
// vocabulary: pending | evaluated | added | applied | dismissed.
export const stageStyle: Record<string, { label: string; color: string; bg: string }> = {
  applied: { label: 'APPLIED', color: '#6FE0EE', bg: 'rgba(0,181,200,.14)' },
  added: { label: 'READY', color: '#6FD3A0', bg: 'rgba(111,211,160,.14)' },
  evaluated: { label: 'ASSESSED', color: '#E0B77A', bg: 'rgba(224,183,122,.14)' },
  pending: { label: 'NEW', color: '#9BB0D0', bg: 'rgba(255,255,255,.06)' },
  dismissed: { label: 'DISMISSED', color: '#8A99B5', bg: 'rgba(255,255,255,.05)' },
}

export const avatarPalette = ['#6FE0EE', '#9BE0C0', '#E0C98A', '#C7A9E8', '#E8A9B4']

export function fmtK(n: number | null | undefined): string {
  const v = Number(n) || 0
  return v >= 1000 ? `${(v / 1000).toFixed(1).replace(/\.0$/, '')}k` : String(v)
}
