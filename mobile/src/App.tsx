// jobContext mobile — capture reality, glance at state. Deep work lives on
// the desktop; this app is the share sheet, the inbox, and the notification.
//
// UI per the design handoff: 6 tabs (Home, Pipeline, Interviews, People,
// Posts, Wellbeing) on a navy-ink theme with cyan active states, plus an
// animated splash while the app boots. The previous Inbox and Settings
// screens stay mounted as chromeless routes (reached from Home) so the
// activity feed and the API-key connect flow keep working unchanged.
import { NavigationContainer, DarkTheme } from '@react-navigation/native'
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs'
import { StatusBar } from 'expo-status-bar'
import * as SplashScreen from 'expo-splash-screen'
import { useEffect, useState } from 'react'
import { ActivityIndicator, Pressable, Text } from 'react-native'
import { SafeAreaProvider, useSafeAreaInsets } from 'react-native-safe-area-context'
import { useShareIntent } from 'expo-share-intent'
import Home from './screens/Home'
import Pipeline from './screens/Pipeline'
import Interviews from './screens/Interviews'
import People from './screens/People'
import Posts from './screens/Posts'
import Wellbeing from './screens/Wellbeing'
import Inbox from './screens/Inbox'
import Settings from './screens/Settings'
import { captureUrl, isConnected } from './api'
import { extractJobPage } from './pageExtract'
import { ensurePushRegistration } from './push'
import { colors } from './theme'
import { setCaptureStatus, useCaptureStatus } from './captureStatus'
import {
  HomeIcon,
  InterviewsIcon,
  PeopleIcon,
  PipelineIcon,
  PostsIcon,
  WellbeingIcon,
} from './ui/icons'
import Splash from './ui/Splash'
import { t } from './ui/tokens'

SplashScreen.preventAutoHideAsync().catch(() => {})

const Tab = createBottomTabNavigator()

const theme = {
  ...DarkTheme,
  colors: {
    ...DarkTheme.colors,
    background: t.bg,
    card: t.bg,
    border: t.hairline,
    text: t.text,
    primary: t.cyan,
  },
}

// Keep the animated splash up until auth state has resolved AND the intro
// timeline has had time to play (bar fill ends ~3.65s into the sequence).
const SPLASH_MIN_MS = 3400

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
    // Read the page here first: the phone's residential IP gets real content
    // where LinkedIn authwalls our cloud. Server falls back if this yields ''.
    extractJobPage(url)
      .then((text) => captureUrl(url, text))
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
  const [booted, setBooted] = useState(false)

  useEffect(() => {
    ensurePushRegistration()
  }, [])
  useEffect(() => {
    // Our animated splash takes over from the native launch screen.
    SplashScreen.hideAsync().catch(() => {})
    Promise.all([
      isConnected().catch(() => false),
      new Promise((resolve) => setTimeout(resolve, SPLASH_MIN_MS)),
    ]).then(() => setBooted(true))
  }, [])

  return (
    <SafeAreaProvider>
      <NavigationContainer theme={theme}>
        <StatusBar style="light" />
        <CaptureBanner />
        <Tab.Navigator
          screenOptions={{
            headerShown: false,
            tabBarStyle: {
              backgroundColor: t.tabBg,
              borderTopColor: t.hairline,
              borderTopWidth: 1,
            },
            tabBarActiveTintColor: t.cyan,
            tabBarInactiveTintColor: t.tabInactive,
            tabBarLabelStyle: { fontSize: 9.5, fontWeight: '500' },
          }}
        >
          <Tab.Screen
            name="Home"
            component={Home}
            options={{ tabBarIcon: ({ color }) => <HomeIcon color={color} /> }}
          />
          <Tab.Screen
            name="Pipeline"
            component={Pipeline}
            options={{ tabBarIcon: ({ color }) => <PipelineIcon color={color} /> }}
          />
          <Tab.Screen
            name="Interviews"
            component={Interviews}
            options={{ tabBarIcon: ({ color }) => <InterviewsIcon color={color} /> }}
          />
          <Tab.Screen
            name="People"
            component={People}
            options={{ tabBarIcon: ({ color }) => <PeopleIcon color={color} /> }}
          />
          <Tab.Screen
            name="Posts"
            component={Posts}
            options={{ tabBarIcon: ({ color }) => <PostsIcon color={color} /> }}
          />
          <Tab.Screen
            name="Wellbeing"
            component={Wellbeing}
            options={{ tabBarIcon: ({ color }) => <WellbeingIcon color={color} /> }}
          />
          {/* Chromeless routes — no tab-bar item; reached from Home. */}
          <Tab.Screen
            name="Activity"
            component={Inbox}
            options={{
              tabBarItemStyle: { display: 'none' },
              headerShown: true,
              headerTitle: 'Activity',
              headerStyle: { backgroundColor: t.bg },
              headerTitleStyle: { color: t.text },
              headerTintColor: t.cyan,
            }}
          />
          <Tab.Screen
            name="Settings"
            component={Settings}
            options={{
              tabBarItemStyle: { display: 'none' },
              headerShown: true,
              headerTitle: 'Settings',
              headerStyle: { backgroundColor: t.bg },
              headerTitleStyle: { color: t.text },
              headerTintColor: t.cyan,
            }}
          />
        </Tab.Navigator>
      </NavigationContainer>
      {!booted && <Splash />}
    </SafeAreaProvider>
  )
}
