// jobContext mobile — capture reality, glance at state. Deep work lives on
// the desktop; this app is the share sheet, the inbox, and the notification.
import { NavigationContainer, DarkTheme } from '@react-navigation/native'
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs'
import { StatusBar } from 'expo-status-bar'
import { useEffect } from 'react'
import { Alert, Text } from 'react-native'
import { useShareIntent } from 'expo-share-intent'
import Inbox from './screens/Inbox'
import Settings from './screens/Settings'
import { captureUrl } from './api'
import { ensurePushRegistration } from './push'
import { colors } from './theme'

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
      Alert.alert('Nothing to capture', 'Share a job posting link.')
      return
    }
    captureUrl(url)
      .then((r) => Alert.alert('Saved', r.detail))
      .catch((e) => Alert.alert('Capture failed', e.message))
  }, [hasShareIntent])
}

export default function App() {
  useIncomingShares()
  useEffect(() => {
    ensurePushRegistration()
  }, [])

  return (
    <NavigationContainer theme={theme}>
      <StatusBar style="light" />
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
          name="Inbox"
          component={Inbox}
          options={{ tabBarIcon: ({ color }) => <Text style={{ color, fontSize: 18 }}>▤</Text> }}
        />
        <Tab.Screen
          name="Settings"
          component={Settings}
          options={{ tabBarIcon: ({ color }) => <Text style={{ color, fontSize: 18 }}>⚙</Text> }}
        />
      </Tab.Navigator>
    </NavigationContainer>
  )
}
