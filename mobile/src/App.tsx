// jobContext mobile — capture reality, glance at state. Deep work lives on
// the desktop; this app is the share sheet, the inbox, and the notification.
import { NavigationContainer, DarkTheme } from '@react-navigation/native'
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs'
import { StatusBar } from 'expo-status-bar'
import { useEffect } from 'react'
import { ActivityIndicator, Pressable, Text } from 'react-native'
import { SafeAreaProvider, useSafeAreaInsets } from 'react-native-safe-area-context'
import { useShareIntent } from 'expo-share-intent'
import Inbox from './screens/Inbox'
import Today from './screens/Today'
import Pipeline from './screens/Pipeline'
import Networking from './screens/Networking'
import Settings from './screens/Settings'
import { captureUrl } from './api'
import { ensurePushRegistration } from './push'
import { colors } from './theme'
import { setCaptureStatus, useCaptureStatus } from './captureStatus'

const Tab = createBottomTabNavigator()

const theme = {
  ...DarkTheme,
  colors: {
    ...DarkTheme.colors,
    background: colors.bg,
    card: colors.surface,
    border: colors.border,
    text: colors.text,
    primary: colors.cyan,
  },
}

function useIncomingShares() {
  const { hasShareIntent, shareIntent, resetShareIntent } = useShareIntent()
  useEffect(() => {
    if (!hasShareIntent) return
    const url =
      shareIntent.webUrl ||
      (shareIntent.text?.match(/https?:\/\/\S+/) || [])[0] ||
      ''
    resetShareIntent()
    if (!url) {
      setCaptureStatus({ kind: 'error', text: 'Nothing to capture — share a job posting link.' })
      return
    }
    setCaptureStatus({ kind: 'busy', text: 'Saving…' })
    captureUrl(url)
      .then((r) => setCaptureStatus({ kind: 'ok', text: `${r.detail} You can keep browsing — a notification arrives with the score.` }, 6000))
      .catch((e) => setCaptureStatus({ kind: 'error', text: e.message }))
  }, [hasShareIntent])
}

function CaptureBanner() {
  const status = useCaptureStatus()
  const insets = useSafeAreaInsets()
  if (!status) return null
  const bg = status.kind === 'error' ? '#3a1b1e' : status.kind === 'ok' ? '#12321f' : colors.surfaceRaised
  const fg = status.kind === 'error' ? colors.danger : status.kind === 'ok' ? colors.green : colors.cyanSoft
  const icon = status.kind === 'error' ? '✕' : status.kind === 'ok' ? '✓' : null
  return (
    <Pressable
      onPress={() => setCaptureStatus(null)}
      style={{
        position: 'absolute',
        top: insets.top + 8,
        left: 12,
        right: 12,
        zIndex: 10,
        flexDirection: 'row',
        alignItems: 'center',
        gap: 10,
        backgroundColor: bg,
        borderColor: colors.border,
        borderWidth: 1,
        borderRadius: 14,
        paddingVertical: 12,
        paddingHorizontal: 14,
        shadowColor: '#000',
        shadowOpacity: 0.45,
        shadowRadius: 12,
        shadowOffset: { width: 0, height: 4 },
        elevation: 8,
      }}
    >
      {icon ? (
        <Text style={{ color: fg, fontSize: 15, fontWeight: '700' }}>{icon}</Text>
      ) : (
        <ActivityIndicator size="small" color={fg} />
      )}
      <Text style={{ color: fg, fontSize: 13, lineHeight: 18, flex: 1 }}>{status.text}</Text>
    </Pressable>
  )
}

export default function App() {
  useIncomingShares()
  useEffect(() => {
    ensurePushRegistration()
  }, [])

  return (
    <SafeAreaProvider>
      <NavigationContainer theme={theme}>
        <StatusBar style="light" />
        <CaptureBanner />
      <Tab.Navigator
        screenOptions={{
          headerStyle: { backgroundColor: colors.surface },
          headerTitleStyle: { color: colors.text },
          tabBarStyle: { backgroundColor: colors.surface, borderTopColor: colors.border },
          tabBarActiveTintColor: colors.cyan,
          tabBarInactiveTintColor: colors.faint,
        }}
      >
        <Tab.Screen
          name="Today"
          component={Today}
          options={{ tabBarIcon: ({ color }) => <Text style={{ color, fontSize: 18 }}>☀</Text> }}
        />
        <Tab.Screen
          name="Inbox"
          component={Inbox}
          options={{ tabBarIcon: ({ color }) => <Text style={{ color, fontSize: 18 }}>▤</Text> }}
        />
        <Tab.Screen
          name="Pipeline"
          component={Pipeline}
          options={{ tabBarIcon: ({ color }) => <Text style={{ color, fontSize: 18 }}>▥</Text> }}
        />
        <Tab.Screen
          name="Networking"
          component={Networking}
          options={{ tabBarIcon: ({ color }) => <Text style={{ color, fontSize: 18 }}>☎</Text> }}
        />
        <Tab.Screen
          name="Settings"
          component={Settings}
          options={{ tabBarIcon: ({ color }) => <Text style={{ color, fontSize: 18 }}>⚙</Text> }}
        />
      </Tab.Navigator>
      </NavigationContainer>
    </SafeAreaProvider>
  )
}
