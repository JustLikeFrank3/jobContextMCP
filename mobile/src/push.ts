// Expo push registration: ask permission, get the Expo token, hand it to the
// cloud so assessment-complete (etc.) notifications can find this device.
import * as Notifications from 'expo-notifications'
import { Platform } from 'react-native'
import { registerPush } from './api'

Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowBanner: true,
    shouldShowList: true,
    shouldPlaySound: true,
    shouldSetBadge: false,
  }),
})

export async function ensurePushRegistration(): Promise<void> {
  try {
    const perms = await Notifications.getPermissionsAsync()
    let status = perms.status
    if (status !== 'granted') {
      status = (await Notifications.requestPermissionsAsync()).status
    }
    if (status !== 'granted') return
    const token = (await Notifications.getExpoPushTokenAsync()).data
    await registerPush(token, Platform.OS)
  } catch {
    // Push is a nicety; never block the app on it.
  }
}
