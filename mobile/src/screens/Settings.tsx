// Settings: cloud URL + personal access token (device keychain) and push.
import { useEffect, useState } from 'react'
import { Alert, Pressable, StyleSheet, Text, TextInput, View } from 'react-native'
import { DEFAULT_URL, fetchEvents, getConfig, setConfig } from '../api'
import { isSignedIn, signIn, signOut } from '../auth'
import { ensurePushRegistration } from '../push'
import { colors } from '../theme'

export default function Settings() {
  const [url, setUrl] = useState('')
  const [pat, setPat] = useState('')
  const [hasPat, setHasPat] = useState(false)
  const [signedIn, setSignedIn] = useState(false)
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    getConfig().then((c) => {
      setUrl(c.url)
      setHasPat(Boolean(c.pat))
    })
    isSignedIn().then(setSignedIn)
  }, [])

  async function microsoftSignIn() {
    setBusy(true)
    try {
      const ok = await signIn(url || DEFAULT_URL)
      if (!ok) throw new Error('Sign-in was cancelled.')
      await fetchEvents()
      await ensurePushRegistration()
      setSignedIn(true)
      Alert.alert('Signed in', 'Inbox and notifications are live.')
    } catch (e: any) {
      Alert.alert('Sign-in failed', e.message)
    } finally {
      setBusy(false)
    }
  }

  async function microsoftSignOut() {
    await signOut()
    setSignedIn(false)
  }

  async function save() {
    setBusy(true)
    try {
      await setConfig(url || DEFAULT_URL, pat)
      await fetchEvents() // proves the key works
      await ensurePushRegistration()
      setPat('')
      setHasPat(true)
      Alert.alert('Connected', 'Signed in — inbox and notifications are live.')
    } catch (e: any) {
      Alert.alert('Could not connect', e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <View style={styles.root}>
      {signedIn ? (
        <Pressable style={[styles.button, styles.ghost]} onPress={microsoftSignOut}>
          <Text style={styles.ghostText}>Signed in with Microsoft — sign out</Text>
        </Pressable>
      ) : (
        <Pressable style={[styles.button, busy && { opacity: 0.6 }]} onPress={microsoftSignIn} disabled={busy}>
          <Text style={styles.buttonText}>{busy ? 'Signing in…' : 'Sign in with Microsoft'}</Text>
        </Pressable>
      )}
      <Pressable onPress={() => setShowAdvanced((v) => !v)}>
        <Text style={styles.advancedToggle}>{showAdvanced ? 'Hide advanced' : 'Advanced: API key'}</Text>
      </Pressable>
      {showAdvanced && (
        <>
      <Text style={styles.label}>Cloud URL</Text>
      <TextInput
        style={styles.input}
        value={url}
        onChangeText={setUrl}
        autoCapitalize="none"
        autoCorrect={false}
        placeholder={DEFAULT_URL}
        placeholderTextColor={colors.faint}
      />
      <Text style={styles.label}>API key</Text>
      <TextInput
        style={styles.input}
        value={pat}
        onChangeText={setPat}
        secureTextEntry
        autoCapitalize="none"
        placeholder={hasPat ? 'Saved — paste to replace' : 'From the dashboard’s API Keys tab'}
        placeholderTextColor={colors.faint}
      />
      <Pressable style={[styles.button, busy && { opacity: 0.6 }]} onPress={save} disabled={busy}>
        <Text style={styles.buttonText}>{busy ? 'Connecting…' : 'Save & connect'}</Text>
      </Pressable>
        </>
      )}
      <Text style={styles.hint}>
        Desktop creates. Mobile captures. Cloud synchronizes. This app talks to your
        cloud workspace — everything you capture here reaches your desktop within a sync.
      </Text>
    </View>
  )
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.bg, padding: 16 },
  label: { color: colors.muted, fontSize: 12, textTransform: 'uppercase', letterSpacing: 1, marginTop: 18, marginBottom: 6 },
  input: {
    backgroundColor: colors.surface, borderColor: colors.border, borderWidth: 1,
    borderRadius: 10, color: colors.text, paddingHorizontal: 14, paddingVertical: 12, fontSize: 15,
  },
  button: {
    backgroundColor: colors.cyan, borderRadius: 10, alignItems: 'center',
    paddingVertical: 13, marginTop: 24,
  },
  buttonText: { color: '#04222a', fontWeight: '700', fontSize: 15 },
  ghost: { backgroundColor: colors.surface, borderColor: colors.border, borderWidth: 1 },
  ghostText: { color: colors.muted, fontSize: 14 },
  advancedToggle: { color: colors.faint, fontSize: 13, textAlign: 'center', marginTop: 18 },
  hint: { color: colors.faint, fontSize: 13, lineHeight: 19, marginTop: 28, textAlign: 'center' },
})
