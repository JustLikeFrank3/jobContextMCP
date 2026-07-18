// Animated launch screen — reproduces the design handoff's splash timeline
// (jobContext Splash.dc.html) with the RN Animated API:
//   badge disc scales in bouncy (.6s, delay .15s) → cyan ring "draws"
//   (approximated: rotate + fade, since react-native-svg is not a dependency)
//   → mark pops in → wordmark rises (1.5s) → tagline (1.95s) → progress bar
//   fills over 2.1s while the mono label blinks.
// Shown as an overlay while the app boots / auth resolves (see App.tsx).
import { useEffect, useRef } from 'react'
import { Animated, Easing, StyleSheet, Text, View } from 'react-native'
import { fonts, t } from './tokens'

const BADGE = 128
const BAR_W = 196

export default function Splash() {
  const disc = useRef(new Animated.Value(0)).current
  const ring = useRef(new Animated.Value(0)).current
  const innerRing = useRef(new Animated.Value(0)).current
  const glow = useRef(new Animated.Value(0)).current
  const markC = useRef(new Animated.Value(0)).current
  const markJ = useRef(new Animated.Value(0)).current
  const word = useRef(new Animated.Value(0)).current
  const tag = useRef(new Animated.Value(0)).current
  const progressBlock = useRef(new Animated.Value(0)).current
  const bar = useRef(new Animated.Value(0)).current
  const blink = useRef(new Animated.Value(0.35)).current

  useEffect(() => {
    const back = Easing.bezier(0.34, 1.56, 0.64, 1) // design's bouncy cubic-bezier
    Animated.parallel([
      Animated.timing(disc, { toValue: 1, duration: 600, delay: 150, easing: back, useNativeDriver: true }),
      Animated.timing(glow, { toValue: 1, duration: 900, delay: 100, useNativeDriver: true }),
      Animated.timing(ring, { toValue: 1, duration: 1000, delay: 450, easing: Easing.ease, useNativeDriver: true }),
      Animated.timing(innerRing, { toValue: 1, duration: 600, delay: 1150, useNativeDriver: true }),
      Animated.timing(markC, { toValue: 1, duration: 500, delay: 950, easing: back, useNativeDriver: true }),
      Animated.timing(markJ, { toValue: 1, duration: 500, delay: 1300, easing: back, useNativeDriver: true }),
      Animated.timing(word, { toValue: 1, duration: 700, delay: 1500, easing: Easing.bezier(0.2, 0.7, 0.2, 1), useNativeDriver: true }),
      Animated.timing(tag, { toValue: 1, duration: 700, delay: 1950, easing: Easing.bezier(0.2, 0.7, 0.2, 1), useNativeDriver: true }),
      Animated.timing(progressBlock, { toValue: 1, duration: 600, delay: 1500, useNativeDriver: true }),
      Animated.timing(bar, { toValue: 1, duration: 2100, delay: 1550, easing: Easing.bezier(0.45, 0.05, 0.2, 1), useNativeDriver: true }),
    ]).start()
    const loop = Animated.loop(
      Animated.sequence([
        Animated.timing(blink, { toValue: 1, duration: 900, useNativeDriver: true }),
        Animated.timing(blink, { toValue: 0.35, duration: 900, useNativeDriver: true }),
      ]),
    )
    loop.start()
    return () => loop.stop()
  }, [])

  const rise = (v: Animated.Value) => ({
    opacity: v,
    transform: [{ translateY: v.interpolate({ inputRange: [0, 1], outputRange: [18, 0] }) }],
  })
  const pop = (v: Animated.Value) => ({
    opacity: v,
    transform: [{ scale: v.interpolate({ inputRange: [0, 1], outputRange: [0.5, 1] }) }],
  })

  return (
    <View style={styles.root}>
      <View style={styles.center}>
        {/* Badge */}
        <View style={styles.badgeWrap}>
          <Animated.View
            style={[
              styles.glow,
              { opacity: glow.interpolate({ inputRange: [0, 1], outputRange: [0, 0.55] }) },
            ]}
          />
          <Animated.View style={[styles.disc, pop(disc)]}>
            {/* Inner faint ring */}
            <Animated.View style={[styles.innerRing, { opacity: innerRing.interpolate({ inputRange: [0, 1], outputRange: [0, 0.35] }) }]} />
            {/* The mark: white j + cyan C (favicon.svg recreated as type — no SVG dep) */}
            <View style={styles.markRow}>
              <Animated.Text style={[styles.markJ, pop(markJ)]}>j</Animated.Text>
              <Animated.Text style={[styles.markC, pop(markC)]}>C</Animated.Text>
            </View>
          </Animated.View>
          {/* Cyan ring: draw approximated by a rotating fade-in of the full ring */}
          <Animated.View
            style={[
              styles.ring,
              {
                opacity: ring,
                transform: [
                  { rotate: ring.interpolate({ inputRange: [0, 1], outputRange: ['-120deg', '0deg'] }) },
                ],
              },
            ]}
          />
        </View>

        {/* Wordmark */}
        <Animated.View style={[styles.wordRow, rise(word)]}>
          <Text style={styles.wordJob}>job</Text>
          <Text style={styles.wordContext}>Context</Text>
        </Animated.View>

        {/* Tagline */}
        <Animated.Text style={[styles.tagline, rise(tag)]}>
          The memory layer for your career.
        </Animated.Text>
      </View>

      {/* Progress block */}
      <Animated.View style={[styles.progressBlock, { opacity: progressBlock }]}>
        <Animated.Text style={[styles.progressLabel, { opacity: blink }]}>
          RESTORING YOUR CONTEXT
        </Animated.Text>
        <View style={styles.track}>
          <Animated.View
            style={[
              styles.fill,
              {
                transform: [
                  // scaleX from the left edge: shift half-width out and back
                  { translateX: bar.interpolate({ inputRange: [0, 1], outputRange: [-BAR_W / 2, 0] }) },
                  { scaleX: bar },
                ],
              },
            ]}
          />
        </View>
      </Animated.View>
    </View>
  )
}

const styles = StyleSheet.create({
  root: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    // Design: linear-gradient(165deg, #0A0F1C, #0B1220) — solid navy without
    // a gradient dependency; the two stops are nearly identical on-device.
    backgroundColor: t.bg,
    alignItems: 'center',
    justifyContent: 'center',
    zIndex: 100,
  },
  center: { alignItems: 'center' },
  badgeWrap: { width: BADGE, height: BADGE, alignItems: 'center', justifyContent: 'center', marginBottom: 40 },
  glow: {
    position: 'absolute',
    width: 200,
    height: 200,
    borderRadius: 100,
    backgroundColor: 'rgba(0,181,200,.22)',
  },
  disc: {
    width: BADGE,
    height: BADGE,
    borderRadius: BADGE / 2,
    backgroundColor: t.bg,
    alignItems: 'center',
    justifyContent: 'center',
    shadowColor: t.cyan,
    shadowOpacity: 0.5,
    shadowRadius: 22,
    shadowOffset: { width: 0, height: 0 },
    elevation: 12,
  },
  ring: {
    position: 'absolute',
    width: BADGE,
    height: BADGE,
    borderRadius: BADGE / 2,
    borderWidth: 4,
    borderColor: t.cyan,
  },
  innerRing: {
    position: 'absolute',
    width: BADGE - 12,
    height: BADGE - 12,
    borderRadius: (BADGE - 12) / 2,
    borderWidth: 1,
    borderColor: t.cyan,
  },
  markRow: { flexDirection: 'row', alignItems: 'center' },
  markJ: { color: '#FFFFFF', fontSize: 56, fontWeight: '700', letterSpacing: -2, fontFamily: fonts.display },
  markC: { color: t.cyan, fontSize: 56, fontWeight: '700', letterSpacing: -2, fontFamily: fonts.display },
  wordRow: { flexDirection: 'row', alignItems: 'baseline' },
  wordJob: { fontSize: 44, fontWeight: '700', letterSpacing: -1.6, color: '#FFFFFF', fontFamily: fonts.display },
  wordContext: { fontSize: 44, fontWeight: '700', letterSpacing: -1.6, color: t.cyan, fontFamily: fonts.display },
  tagline: { marginTop: 14, fontSize: 15, fontWeight: '500', color: '#D7E3F8', opacity: 0.82, letterSpacing: 0.1 },
  progressBlock: { position: 'absolute', bottom: 84, alignItems: 'center', gap: 16 },
  progressLabel: {
    fontFamily: fonts.mono,
    fontSize: 11,
    fontWeight: '500',
    letterSpacing: 3,
    color: t.cyanBright,
  },
  track: {
    width: BAR_W,
    height: 4,
    borderRadius: 999,
    backgroundColor: 'rgba(215,227,248,.12)',
    overflow: 'hidden',
  },
  fill: {
    height: '100%',
    width: BAR_W,
    borderRadius: 999,
    backgroundColor: t.cyan,
  },
})
