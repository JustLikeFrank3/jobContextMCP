// Tab-bar line icons. The design uses currentColor stroke SVGs; react-native-svg
// is not a dependency, so these approximate the same 22px line icons with
// border-drawn Views tinted by the navigator's color prop.
import { View } from 'react-native'

type P = { color: string; size?: number }
const W = 1.8 // stroke width

export function HomeIcon({ color, size = 22 }: P) {
  return (
    <View style={{ width: size, height: size, alignItems: 'center', justifyContent: 'flex-end' }}>
      <View
        style={{
          position: 'absolute',
          top: 2,
          width: size * 0.56,
          height: size * 0.56,
          borderTopWidth: W,
          borderLeftWidth: W,
          borderColor: color,
          transform: [{ rotate: '45deg' }],
        }}
      />
      <View
        style={{
          width: size * 0.55,
          height: size * 0.42,
          borderLeftWidth: W,
          borderRightWidth: W,
          borderBottomWidth: W,
          borderColor: color,
        }}
      />
    </View>
  )
}

export function PipelineIcon({ color, size = 22 }: P) {
  const row = (key: number) => (
    <View key={key} style={{ flexDirection: 'row', alignItems: 'center', gap: 4 }}>
      <View style={{ width: 4, height: 4, borderRadius: 2, borderWidth: 1.4, borderColor: color }} />
      <View style={{ flex: 1, height: W, borderRadius: 1, backgroundColor: color }} />
    </View>
  )
  return (
    <View style={{ width: size, height: size, justifyContent: 'space-evenly', paddingVertical: 2 }}>
      {[0, 1, 2].map(row)}
    </View>
  )
}

export function InterviewsIcon({ color, size = 22 }: P) {
  return (
    <View style={{ width: size, height: size, alignItems: 'center', justifyContent: 'center' }}>
      <View
        style={{
          width: size * 0.78,
          height: size * 0.68,
          borderWidth: W,
          borderColor: color,
          borderRadius: 3.5,
          marginTop: 3,
        }}
      >
        <View style={{ height: size * 0.16, borderBottomWidth: W, borderColor: color }} />
      </View>
      <View style={{ position: 'absolute', top: 1, left: size * 0.3, width: W, height: 5, backgroundColor: color }} />
      <View style={{ position: 'absolute', top: 1, right: size * 0.3, width: W, height: 5, backgroundColor: color }} />
    </View>
  )
}

export function PeopleIcon({ color, size = 22 }: P) {
  return (
    <View style={{ width: size, height: size }}>
      <View
        style={{
          position: 'absolute',
          top: 1,
          left: 3,
          width: size * 0.34,
          height: size * 0.34,
          borderRadius: size * 0.17,
          borderWidth: W,
          borderColor: color,
        }}
      />
      <View
        style={{
          position: 'absolute',
          bottom: 1,
          left: 0,
          width: size * 0.56,
          height: size * 0.3,
          borderTopLeftRadius: size * 0.28,
          borderTopRightRadius: size * 0.28,
          borderTopWidth: W,
          borderLeftWidth: W,
          borderRightWidth: W,
          borderColor: color,
        }}
      />
      <View
        style={{
          position: 'absolute',
          top: 4,
          right: 2,
          width: size * 0.24,
          height: size * 0.24,
          borderRadius: size * 0.12,
          borderWidth: 1.5,
          borderColor: color,
          opacity: 0.85,
        }}
      />
      <View
        style={{
          position: 'absolute',
          bottom: 1,
          right: 0,
          width: size * 0.34,
          height: size * 0.22,
          borderTopLeftRadius: size * 0.18,
          borderTopRightRadius: size * 0.18,
          borderTopWidth: 1.5,
          borderRightWidth: 1.5,
          borderColor: color,
          opacity: 0.85,
        }}
      />
    </View>
  )
}

export function PostsIcon({ color, size = 22 }: P) {
  const ring = (d: number, o: number) => (
    <View
      key={d}
      style={{
        position: 'absolute',
        width: d,
        height: d,
        borderRadius: d / 2,
        borderWidth: 1.5,
        borderColor: color,
        opacity: o,
      }}
    />
  )
  return (
    <View style={{ width: size, height: size, alignItems: 'center', justifyContent: 'center' }}>
      {ring(size * 0.95, 0.45)}
      {ring(size * 0.6, 0.75)}
      <View style={{ width: 5, height: 5, borderRadius: 2.5, backgroundColor: color }} />
    </View>
  )
}

export function WellbeingIcon({ color, size = 22 }: P) {
  // A line heart is not drawable with plain View borders, so this one is the
  // filled silhouette (two lobes + rotated square) in the tint color.
  const lobe = size * 0.38
  return (
    <View style={{ width: size, height: size, alignItems: 'center', justifyContent: 'center' }}>
      <View style={{ width: size * 0.72, height: size * 0.66 }}>
        <View
          style={{
            position: 'absolute',
            top: 0,
            left: 0,
            width: lobe,
            height: lobe,
            borderRadius: lobe / 2,
            backgroundColor: color,
          }}
        />
        <View
          style={{
            position: 'absolute',
            top: 0,
            right: 0,
            width: lobe,
            height: lobe,
            borderRadius: lobe / 2,
            backgroundColor: color,
          }}
        />
        <View
          style={{
            position: 'absolute',
            top: lobe * 0.32,
            left: (size * 0.72 - lobe * 1.02) / 2,
            width: lobe * 1.02,
            height: lobe * 1.02,
            backgroundColor: color,
            transform: [{ rotate: '45deg' }],
          }}
        />
      </View>
    </View>
  )
}
