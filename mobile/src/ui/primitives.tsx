// Shared building blocks for the design screens: screen shell with the
// jc-screenIn enter animation, section labels, cards, chips, and the
// loading / error / empty states every data screen shares.
import { useFocusEffect } from '@react-navigation/native'
import { ReactNode, useCallback, useRef } from 'react'
import {
  ActivityIndicator,
  Animated,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  View,
  ViewStyle,
} from 'react-native'
import { useSafeAreaInsets } from 'react-native-safe-area-context'
import { fonts, t } from './tokens'

/** Screen shell: navy bg, safe-area padding, pull-to-refresh, and the
 *  design's fade + rise (translateY 10 → 0, .3s) on every tab focus. */
export function Screen({
  children,
  refreshing = false,
  onRefresh,
}: {
  children: ReactNode
  refreshing?: boolean
  onRefresh?: () => void
}) {
  const insets = useSafeAreaInsets()
  const anim = useRef(new Animated.Value(0)).current
  useFocusEffect(
    useCallback(() => {
      anim.setValue(0)
      Animated.timing(anim, { toValue: 1, duration: 300, useNativeDriver: true }).start()
    }, [anim]),
  )
  return (
    <View style={styles.root}>
      <ScrollView
        style={{ flex: 1 }}
        contentContainerStyle={{ paddingTop: insets.top + 14, paddingHorizontal: 18, paddingBottom: 28 }}
        showsVerticalScrollIndicator={false}
        refreshControl={
          onRefresh ? <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={t.cyan} /> : undefined
        }
      >
        <Animated.View
          style={{
            opacity: anim,
            transform: [{ translateY: anim.interpolate({ inputRange: [0, 1], outputRange: [10, 0] }) }],
          }}
        >
          {children}
        </Animated.View>
      </ScrollView>
    </View>
  )
}

export function ScreenTitle({ children, sub }: { children: string; sub?: string }) {
  return (
    <View>
      <Text style={styles.title}>{children}</Text>
      {sub ? <Text style={styles.titleSub}>{sub}</Text> : null}
    </View>
  )
}

/** Mono uppercase micro-label ("FOLLOW-UPS DUE"). */
export function SectionLabel({ children, style }: { children: string; style?: ViewStyle }) {
  return <Text style={[styles.section, style as any]}>{children}</Text>
}

export function Card({
  children,
  tint,
  raised,
  style,
}: {
  children: ReactNode
  /** cyan-tinted accent card */
  tint?: 'low' | 'high'
  raised?: boolean
  style?: ViewStyle
}) {
  const base: ViewStyle = tint
    ? {
        backgroundColor: tint === 'high' ? t.tintFillHi : t.tintFillLo,
        borderColor: tint === 'high' ? t.tintBorderHi : t.tintBorderLo,
      }
    : {
        backgroundColor: raised ? t.cardRaised : t.card,
        borderColor: raised ? t.cardBorderRaised : t.cardBorder,
      }
  return <View style={[styles.card, base, style]}>{children}</View>
}

/** Pill chip; active = solid cyan with ink text (design segmented chips). */
export function Chip({
  label,
  active,
  onPress,
}: {
  label: string
  active?: boolean
  onPress?: () => void
}) {
  return (
    <Pressable
      onPress={onPress}
      style={[styles.chip, { backgroundColor: active ? t.cyan : t.chipBg }]}
    >
      <Text style={[styles.chipText, { color: active ? t.cyanInk : t.textSecondary }]}>{label}</Text>
    </Pressable>
  )
}

/** Small mono status chip (e.g. "5D OVERDUE", stage chips). */
export function StatusChip({ label, color, bg }: { label: string; color: string; bg: string }) {
  return (
    <View style={[styles.statusChip, { backgroundColor: bg }]}>
      <Text style={[styles.statusChipText, { color }]}>{label}</Text>
    </View>
  )
}

export function StatTile({
  value,
  label,
  accent,
}: {
  value: string | number
  label: string
  accent?: boolean
}) {
  return (
    <View
      style={[
        styles.statTile,
        accent
          ? { backgroundColor: t.tintFill, borderColor: 'rgba(0,181,200,.22)' }
          : { backgroundColor: t.card, borderColor: t.cardBorder },
      ]}
    >
      <Text style={[styles.statValue, { color: accent ? t.cyanBright : t.text }]}>{value}</Text>
      <Text style={[styles.statLabel, { color: accent ? t.cyanMuted : t.muted }]}>{label}</Text>
    </View>
  )
}

export function LoadingState() {
  return (
    <View style={styles.centerBox}>
      <ActivityIndicator color={t.cyan} />
      <Text style={styles.centerText}>Loading…</Text>
    </View>
  )
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <View style={styles.centerBox}>
      <Text style={styles.errorText}>{message}</Text>
      {onRetry ? (
        <Pressable onPress={onRetry} style={styles.retry}>
          <Text style={styles.retryText}>Try again</Text>
        </Pressable>
      ) : null}
    </View>
  )
}

export function EmptyState({ message }: { message: string }) {
  return (
    <View style={styles.centerBox}>
      <Text style={styles.centerText}>{message}</Text>
    </View>
  )
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: t.bg },
  title: { fontSize: 27, fontWeight: '700', color: t.text, letterSpacing: -0.6, fontFamily: fonts.display },
  titleSub: { fontSize: 13, color: t.muted, marginTop: 2 },
  section: {
    fontSize: 12,
    fontWeight: '600',
    letterSpacing: 1.2,
    color: t.muted2,
    fontFamily: fonts.mono,
    textTransform: 'uppercase',
    marginTop: 22,
  },
  card: { borderRadius: 16, padding: 15, borderWidth: 1, marginTop: 10 },
  chip: { paddingHorizontal: 14, paddingVertical: 7, borderRadius: 999 },
  chipText: { fontSize: 12.5, fontWeight: '600' },
  statusChip: { paddingHorizontal: 8, paddingVertical: 4, borderRadius: 8 },
  statusChipText: { fontSize: 10.5, fontWeight: '600', fontFamily: fonts.mono, letterSpacing: 0.5 },
  statTile: { flex: 1, borderRadius: 16, padding: 13, borderWidth: 1, alignItems: 'center' },
  statValue: { fontSize: 20, fontWeight: '700' },
  statLabel: { fontSize: 10.5, marginTop: 2 },
  centerBox: { alignItems: 'center', paddingVertical: 48, gap: 10 },
  centerText: { color: t.muted, fontSize: 13, textAlign: 'center', lineHeight: 19, paddingHorizontal: 24 },
  errorText: { color: t.red, fontSize: 13, textAlign: 'center', lineHeight: 19, paddingHorizontal: 24 },
  retry: {
    backgroundColor: t.tintFill,
    borderColor: t.tintBorder,
    borderWidth: 1,
    borderRadius: 10,
    paddingHorizontal: 16,
    paddingVertical: 8,
  },
  retryText: { color: t.cyanBright, fontSize: 13, fontWeight: '600' },
})
