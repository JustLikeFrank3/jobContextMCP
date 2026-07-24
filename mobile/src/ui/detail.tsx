// Universal detail-page kit. Every object card in the app pushes one of
// these pages onto the root stack; they all share the same skeleton so the
// app reads as one system: kicker + large title + hero, pinned summary
// block, collapsible sections, meta grid, timeline, related rows, and a
// quick-action row. Cards use PressableScale for the spring press-feedback.
import { useNavigation } from '@react-navigation/native'
import { ReactNode, useRef, useState } from 'react'
import {
  Animated,
  LayoutAnimation,
  Platform,
  Pressable,
  RefreshControl,
  ScrollView,
  Share,
  StyleSheet,
  Text,
  UIManager,
  View,
  ViewStyle,
} from 'react-native'
import { useSafeAreaInsets } from 'react-native-safe-area-context'
import { fonts, t } from './tokens'

if (Platform.OS === 'android' && UIManager.setLayoutAnimationEnabledExperimental) {
  UIManager.setLayoutAnimationEnabledExperimental(true)
}

/** Spring scale-down on press — the "card press" animation used everywhere. */
export function PressableScale({
  children,
  onPress,
  onLongPress,
  style,
  disabled,
}: {
  children: ReactNode
  onPress?: () => void
  onLongPress?: () => void
  style?: ViewStyle
  disabled?: boolean
}) {
  const scale = useRef(new Animated.Value(1)).current
  const to = (v: number) =>
    Animated.spring(scale, { toValue: v, useNativeDriver: true, speed: 40, bounciness: 6 }).start()
  return (
    <Pressable
      onPress={onPress}
      onLongPress={onLongPress}
      disabled={disabled}
      onPressIn={() => to(0.97)}
      onPressOut={() => to(1)}
    >
      <Animated.View style={[style, { transform: [{ scale }] }]}>{children}</Animated.View>
    </Pressable>
  )
}

/** Full-screen shell for a pushed detail page: back chevron, share button,
 *  mono kicker ("JOB" / "RECRUITER"), large title, optional hero line. */
export function DetailShell({
  kicker,
  title,
  subtitle,
  shareText,
  children,
  refreshing = false,
  onRefresh,
}: {
  kicker: string
  title: string
  subtitle?: string
  /** When set, the ↗ button opens the native share sheet with this text. */
  shareText?: string
  children: ReactNode
  refreshing?: boolean
  onRefresh?: () => void
}) {
  const nav = useNavigation<any>()
  const insets = useSafeAreaInsets()
  return (
    <View style={styles.root}>
      <ScrollView
        style={{ flex: 1 }}
        contentContainerStyle={{ paddingTop: insets.top + 8, paddingHorizontal: 18, paddingBottom: 36 }}
        showsVerticalScrollIndicator={false}
        refreshControl={
          onRefresh ? <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={t.cyan} /> : undefined
        }
      >
        <View style={styles.navRow}>
          <Pressable onPress={() => nav.goBack()} hitSlop={12} style={styles.navBtn}>
            <Text style={styles.navBtnText}>‹</Text>
          </Pressable>
          {shareText ? (
            <Pressable
              onPress={() => Share.share({ message: shareText }).catch(() => {})}
              hitSlop={12}
              style={styles.navBtn}
            >
              <Text style={[styles.navBtnText, { fontSize: 17 }]}>↗</Text>
            </Pressable>
          ) : null}
        </View>
        <Text style={styles.kicker}>{kicker.toUpperCase()}</Text>
        <Text style={styles.title}>{title}</Text>
        {subtitle ? <Text style={styles.subtitle}>{subtitle}</Text> : null}
        {children}
      </ScrollView>
    </View>
  )
}

/** The pinned executive-summary block. Always expanded, opens every page. */
export function SummaryBlock({ sentences }: { sentences: string[] }) {
  if (!sentences.length) return null
  return (
    <View style={styles.summary}>
      <Text style={styles.summaryLabel}>◈ SUMMARY</Text>
      <Text style={styles.summaryText}>{sentences.join(' ')}</Text>
    </View>
  )
}

/** Collapsible section — everything below the summary folds. */
export function Section({
  label,
  count,
  initiallyOpen = true,
  children,
}: {
  label: string
  count?: number
  initiallyOpen?: boolean
  children: ReactNode
}) {
  const [open, setOpen] = useState(initiallyOpen)
  const toggle = () => {
    LayoutAnimation.configureNext(LayoutAnimation.Presets.easeInEaseOut)
    setOpen((o) => !o)
  }
  return (
    <View style={{ marginTop: 22 }}>
      <Pressable onPress={toggle} style={styles.sectionRow} hitSlop={6}>
        <Text style={styles.sectionLabel}>
          {label.toUpperCase()}
          {count != null ? `  ·  ${count}` : ''}
        </Text>
        <Text style={[styles.sectionChevron, open && { transform: [{ rotate: '90deg' }] }]}>›</Text>
      </Pressable>
      {open ? children : null}
    </View>
  )
}

/** Label/value rows for object metadata. */
export function MetaGrid({ rows }: { rows: { label: string; value?: string | number | null }[] }) {
  const shown = rows.filter((r) => r.value !== undefined && r.value !== null && String(r.value).trim() !== '')
  if (!shown.length) return null
  return (
    <View style={styles.metaCard}>
      {shown.map((r, i) => (
        <View key={r.label} style={[styles.metaRow, i > 0 && styles.metaRowBorder]}>
          <Text style={styles.metaLabel}>{r.label.toUpperCase()}</Text>
          <Text style={styles.metaValue} numberOfLines={2}>
            {String(r.value)}
          </Text>
        </View>
      ))}
    </View>
  )
}

export type TimelineItem = { title: string; sub?: string; ts?: string; color?: string }

/** Vertical dotted timeline used for "what happened" on every page. */
export function TimelineList({ items }: { items: TimelineItem[] }) {
  if (!items.length) return null
  return (
    <View style={{ marginTop: 10 }}>
      {items.map((it, i) => (
        <View key={`${it.title}${i}`} style={styles.tlRow}>
          <View style={styles.tlRail}>
            <View style={[styles.tlDot, { backgroundColor: it.color || t.cyan }]} />
            {i < items.length - 1 ? <View style={styles.tlLine} /> : null}
          </View>
          <View style={{ flex: 1, paddingBottom: i < items.length - 1 ? 14 : 0 }}>
            <View style={styles.tlTop}>
              <Text style={styles.tlTitle}>{it.title}</Text>
              {it.ts ? <Text style={styles.tlTs}>{it.ts.slice(0, 10)}</Text> : null}
            </View>
            {it.sub ? (
              <Text style={styles.tlSub} numberOfLines={2}>
                {it.sub}
              </Text>
            ) : null}
          </View>
        </View>
      ))}
    </View>
  )
}

/** Compact tappable row for related objects — never a dead end. */
export function RelatedRow({
  title,
  sub,
  right,
  onPress,
}: {
  title: string
  sub?: string
  right?: string
  onPress?: () => void
}) {
  return (
    <PressableScale onPress={onPress} style={styles.relatedRow}>
      <View style={{ flex: 1, minWidth: 0 }}>
        <Text style={styles.relatedTitle} numberOfLines={1}>
          {title}
        </Text>
        {sub ? (
          <Text style={styles.relatedSub} numberOfLines={1}>
            {sub}
          </Text>
        ) : null}
      </View>
      {right ? <Text style={styles.relatedRight}>{right}</Text> : null}
      {onPress ? <Text style={styles.relatedArrow}>›</Text> : null}
    </PressableScale>
  )
}

/** Wrapping row of quick-action pills that ends every detail page. */
export function ActionRow({
  actions,
}: {
  actions: { label: string; onPress: () => void; primary?: boolean }[]
}) {
  if (!actions.length) return null
  return (
    <View style={styles.actionRow}>
      {actions.map((a) => (
        <PressableScale
          key={a.label}
          onPress={a.onPress}
          style={[styles.actionBtn, a.primary ? styles.actionPrimary : null] as unknown as ViewStyle}
        >
          <Text style={[styles.actionText, a.primary && { color: t.cyanInk }]}>{a.label}</Text>
        </PressableScale>
      ))}
    </View>
  )
}

/** Bullet list (strengths / weaknesses / priorities). */
export function Bullets({ items, color }: { items: string[]; color?: string }) {
  if (!items.length) return null
  return (
    <View style={styles.bullets}>
      {items.map((b, i) => (
        <View key={i} style={styles.bulletRow}>
          <View style={[styles.bulletDot, { backgroundColor: color || t.cyan }]} />
          <Text style={styles.bulletText}>{b}</Text>
        </View>
      ))}
    </View>
  )
}

/** Labeled meter (energy, self-rating, engagement) 0..max. */
export function Meter({ label, value, max = 10 }: { label: string; value: number; max?: number }) {
  return (
    <View style={styles.meterRow}>
      <Text style={styles.meterLabel}>{label.toUpperCase()}</Text>
      <View style={styles.meterTrack}>
        <View style={[styles.meterFill, { width: `${Math.min(100, (value / max) * 100)}%` }]} />
      </View>
      <Text style={styles.meterVal}>
        {value}/{max}
      </Text>
    </View>
  )
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: t.bg },
  navRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 },
  navBtn: {
    width: 36,
    height: 36,
    borderRadius: 18,
    backgroundColor: t.chipBg,
    borderWidth: 1,
    borderColor: t.cardBorder,
    alignItems: 'center',
    justifyContent: 'center',
  },
  navBtnText: { color: t.textBright, fontSize: 22, lineHeight: 24, fontWeight: '600' },
  kicker: { fontSize: 11, fontWeight: '600', letterSpacing: 1.5, color: t.cyanBright, fontFamily: fonts.mono },
  title: { fontSize: 28, fontWeight: '700', color: t.text, letterSpacing: -0.6, marginTop: 4 },
  subtitle: { fontSize: 14, color: t.muted, marginTop: 4, lineHeight: 20 },
  summary: {
    marginTop: 18,
    borderRadius: 18,
    padding: 16,
    backgroundColor: t.tintFillHi,
    borderWidth: 1,
    borderColor: t.tintBorderHi,
  },
  summaryLabel: { fontSize: 10.5, fontWeight: '600', letterSpacing: 1.5, color: t.cyanBright, fontFamily: fonts.mono },
  summaryText: { marginTop: 8, fontSize: 14, color: t.textBright, lineHeight: 21 },
  sectionRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  sectionLabel: {
    fontSize: 12,
    fontWeight: '600',
    letterSpacing: 1.2,
    color: t.muted2,
    fontFamily: fonts.mono,
  },
  sectionChevron: { color: t.muted2, fontSize: 16, fontWeight: '700' },
  metaCard: {
    marginTop: 10,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: t.cardBorder,
    backgroundColor: t.card,
    paddingHorizontal: 15,
  },
  metaRow: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingVertical: 12 },
  metaRowBorder: { borderTopWidth: 1, borderTopColor: t.hairline },
  metaLabel: { width: 96, fontSize: 10.5, color: t.muted2, fontFamily: fonts.mono, letterSpacing: 0.8 },
  metaValue: { flex: 1, fontSize: 13.5, color: t.textBright, textAlign: 'right' },
  tlRow: { flexDirection: 'row', gap: 12 },
  tlRail: { width: 10, alignItems: 'center' },
  tlDot: { width: 8, height: 8, borderRadius: 4, marginTop: 5 },
  tlLine: { flex: 1, width: 1.5, backgroundColor: 'rgba(255,255,255,.09)', marginTop: 3 },
  tlTop: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 10 },
  tlTitle: { fontSize: 13.5, fontWeight: '600', color: t.textBright, flex: 1 },
  tlTs: { fontSize: 10.5, color: t.faint, fontFamily: fonts.mono },
  tlSub: { fontSize: 12.5, color: t.muted, marginTop: 2, lineHeight: 17 },
  relatedRow: {
    marginTop: 8,
    borderRadius: 14,
    paddingVertical: 12,
    paddingHorizontal: 14,
    backgroundColor: t.card,
    borderWidth: 1,
    borderColor: t.cardBorder,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
  },
  relatedTitle: { fontSize: 14, fontWeight: '600', color: t.text },
  relatedSub: { fontSize: 12, color: t.muted, marginTop: 1 },
  relatedRight: { fontSize: 11, color: t.cyanBright, fontFamily: fonts.mono, fontWeight: '600' },
  relatedArrow: { fontSize: 16, color: t.muted2 },
  actionRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginTop: 10 },
  actionBtn: {
    backgroundColor: t.tintFillLo,
    borderColor: t.tintBorderLo,
    borderWidth: 1,
    borderRadius: 11,
    paddingHorizontal: 15,
    paddingVertical: 9,
  },
  actionPrimary: { backgroundColor: t.cyan, borderColor: t.cyan },
  actionText: { color: t.cyanBright, fontSize: 13, fontWeight: '600' },
  bullets: { marginTop: 10, gap: 8 },
  bulletRow: { flexDirection: 'row', gap: 10, alignItems: 'flex-start' },
  bulletDot: { width: 6, height: 6, borderRadius: 3, marginTop: 6 },
  bulletText: { flex: 1, fontSize: 13.5, color: t.textBody, lineHeight: 19 },
  meterRow: { flexDirection: 'row', alignItems: 'center', gap: 10, marginTop: 10 },
  meterLabel: { width: 110, fontSize: 9.5, color: t.muted2, fontFamily: fonts.mono, letterSpacing: 1 },
  meterTrack: { flex: 1, height: 6, borderRadius: 3, backgroundColor: 'rgba(255,255,255,.07)', overflow: 'hidden' },
  meterFill: { height: '100%', borderRadius: 3, backgroundColor: t.cyan },
  meterVal: { width: 44, fontSize: 11, fontWeight: '600', color: t.textSecondary, fontFamily: fonts.mono, textAlign: 'right' },
})
