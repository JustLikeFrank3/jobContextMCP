import { readFileSync } from 'node:fs'
import { runInNewContext } from 'node:vm'
import { transformSync } from 'esbuild'
import { afterEach, expect, test, vi } from 'vitest'

// Exercise the actual native-source effects without an emulator or native
// package initialization. Only platform imports/rendering are replaced; the
// app's promise chains and push error boundary execute unchanged.
function loadMobile(relativePath, modules) {
  const filename = new URL(`../../mobile/src/${relativePath}`, import.meta.url)
  const { code } = transformSync(readFileSync(filename, 'utf8'), {
    loader: relativePath.endsWith('.tsx') ? 'tsx' : 'ts',
    format: 'cjs',
    jsx: 'automatic',
  })
  const module = { exports: {} }
  runInNewContext(code, {
    module,
    exports: module.exports,
    require(name) {
      if (name in modules) return modules[name]
      if (name === 'react/jsx-runtime') return { jsx: () => null, jsxs: () => null }
      if (name.startsWith('./screens/') || name === './ui/Splash') {
        return { __esModule: true, default: () => null }
      }
      throw new Error(`Unstubbed native dependency: ${name}`)
    },
    setTimeout: (...args) => setTimeout(...args),
  }, { filename: filename.pathname })
  return module.exports
}

function hooks() {
  const effects = []
  const states = []
  return {
    effects,
    states,
    react: {
      useEffect: (effect) => effects.push(effect),
      useState: (initial) => {
        const setter = vi.fn()
        states.push({ initial, setter })
        return [initial, setter]
      },
    },
  }
}

afterEach(() => vi.useRealTimers())

function loadApp(isConnected) {
  const captured = hooks()
  const navigator = () => ({ Navigator: () => null, Screen: () => null })
  const ensurePushRegistration = vi.fn().mockResolvedValue(undefined)
  const { default: App } = loadMobile('App.tsx', {
    react: captured.react,
    '@react-navigation/native': { DarkTheme: { colors: {} } },
    '@react-navigation/bottom-tabs': { createBottomTabNavigator: navigator },
    '@react-navigation/native-stack': { createNativeStackNavigator: navigator },
    'expo-status-bar': {},
    'expo-splash-screen': {
      preventAutoHideAsync: vi.fn().mockResolvedValue(undefined),
      hideAsync: vi.fn().mockResolvedValue(undefined),
    },
    'react-native': {},
    'react-native-safe-area-context': {},
    'expo-share-intent': { useShareIntent: () => ({ hasShareIntent: false }) },
    './api': { isConnected },
    './pageExtract': {},
    './push': { ensurePushRegistration },
    './theme': { colors: {} },
    './captureStatus': {},
    './ui/icons': {},
    './ui/tokens': { t: {} },
  })
  App()
  captured.effects.forEach((effect) => effect())
  return { setBooted: captured.states[0].setter, ensurePushRegistration }
}

test.each([true, false])('mobile boot waits for the intro when keychain read succeeds=%s', async (success) => {
  vi.useFakeTimers()
  const isConnected = success
    ? vi.fn().mockResolvedValue(true)
    : vi.fn().mockRejectedValue(new Error('keychain unavailable'))
  const { setBooted, ensurePushRegistration } = loadApp(isConnected)
  expect(ensurePushRegistration).toHaveBeenCalledOnce()
  await vi.advanceTimersByTimeAsync(3399)
  expect(setBooted).not.toHaveBeenCalled()
  await vi.advanceTimersByTimeAsync(1)
  expect(setBooted).toHaveBeenCalledExactlyOnceWith(true)
})

test('mobile boot also waits for a slow keychain read', async () => {
  vi.useFakeTimers()
  let finishRead
  const isConnected = vi.fn(() => new Promise((resolve) => { finishRead = resolve }))
  const { setBooted } = loadApp(isConnected)
  await vi.advanceTimersByTimeAsync(3400)
  expect(setBooted).not.toHaveBeenCalled()
  finishRead(false)
  await vi.advanceTimersByTimeAsync(0)
  expect(setBooted).toHaveBeenCalledExactlyOnceWith(true)
})

test.each(['permissions', 'permissionRequest', 'token', 'registration'])('push %s rejection is contained by the registration contract', async (stage) => {
  const failure = new Error('native or network failure')
  const notifications = {
    setNotificationHandler: vi.fn(),
    getPermissionsAsync: vi.fn().mockResolvedValue({ status: 'undetermined' }),
    requestPermissionsAsync: vi.fn().mockResolvedValue({ status: 'granted' }),
    getExpoPushTokenAsync: vi.fn().mockResolvedValue({ data: 'synthetic-token' }),
  }
  const registerPush = vi.fn().mockResolvedValue(undefined)
  const stages = {
    permissions: notifications.getPermissionsAsync,
    permissionRequest: notifications.requestPermissionsAsync,
    token: notifications.getExpoPushTokenAsync,
    registration: registerPush,
  }
  stages[stage].mockRejectedValue(failure)
  const { ensurePushRegistration } = loadMobile('push.ts', {
    'expo-notifications': notifications,
    'react-native': { Platform: { OS: 'ios' } },
    './api': { registerPush },
  })
  await expect(ensurePushRegistration()).resolves.toBeUndefined()
  expect(stages[stage]).toHaveBeenCalledOnce()
  if (stage !== 'registration') expect(registerPush).not.toHaveBeenCalled()
})

function loadSettings(getConfig) {
  const captured = hooks()
  const alert = vi.fn()
  const { default: Settings } = loadMobile('screens/Settings.tsx', {
    react: captured.react,
    'react-native': { Alert: { alert }, StyleSheet: { create: (styles) => styles } },
    '../api': { getConfig },
    '../push': {},
    '../theme': { colors: {} },
  })
  Settings()
  captured.effects.forEach((effect) => effect())
  return { ...captured, alert }
}

test('settings loads connection state without copying the saved PAT into the input', async () => {
  const getConfig = vi.fn().mockResolvedValue({ url: 'https://example.test', pat: 'synthetic-private-pat' })
  const { states, alert } = loadSettings(getConfig)
  await vi.waitFor(() => expect(states[0].setter).toHaveBeenCalledWith('https://example.test'))
  expect(states[2].setter).toHaveBeenCalledWith(true)
  expect(states[1].setter).not.toHaveBeenCalled()
  expect(alert).not.toHaveBeenCalled()
})

test('settings reports failed keychain reads without leaking their contents or changing connection state', async () => {
  const getConfig = vi.fn().mockRejectedValue(new Error('synthetic-private-pat'))
  const { states, alert } = loadSettings(getConfig)
  await vi.waitFor(() => expect(alert).toHaveBeenCalledExactlyOnceWith(
    'Could not load settings',
    'Your saved connection could not be read. Reopen Settings to try again.',
  ))
  expect(JSON.stringify(alert.mock.calls)).not.toContain('synthetic-private-pat')
  states.forEach(({ setter }) => expect(setter).not.toHaveBeenCalled())
})
