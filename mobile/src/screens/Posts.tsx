// Posts — design layout: aggregate metrics strip + post cards (text,
// hashtags, view/reaction/comment counts, Update button) with the
// bottom-sheet Update-metrics editor. CSV import stays on desktop.
// Data: GET /dashboard/posts/data; updates via POST /dashboard/posts/metrics.
// The design's "Followers" tile has no counterpart in the payload, so the
// strip shows Comments instead.
import { useNavigation } from '@react-navigation/native'
import { useCallback, useState } from 'react'
import { KeyboardAvoidingView, Modal, Platform, Pressable, StyleSheet, Text, TextInput, View } from 'react-native'
import { api } from '../api'
import { PressableScale } from '../ui/detail'
import {
  Card,
  EmptyState,
  ErrorState,
  LoadingState,
  Screen,
  ScreenTitle,
  StatTile,
} from '../ui/primitives'
import { fmtK, fonts, t } from '../ui/tokens'
import { useDashData } from '../ui/useDashData'

type Post = {
  id: number
  text: string
  title?: string
  posted_date?: string
  hashtags?: string[]
  impressions: number
  reactions: number
  comments: number
}

type Payload = {
  total: number
  total_impressions: number
  total_reactions: number
  total_comments: number
  posts: Post[]
}

type Draft = { imp: string; rx: string; cm: string }

function digitsOnly(v: string): string {
  return v.replace(/[^0-9]/g, '')
}

export default function Posts() {
  const nav = useNavigation<any>()
  const load = useCallback(() => api<Payload>('/dashboard/posts/data'), [])
  const { data, loading, refreshing, error, refresh } = useDashData(load)

  const [sheetPost, setSheetPost] = useState<Post | null>(null)
  const [draft, setDraft] = useState<Draft>({ imp: '', rx: '', cm: '' })
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState('')

  const openSheet = (p: Post) => {
    setSheetPost(p)
    setDraft({ imp: String(p.impressions || 0), rx: String(p.reactions || 0), cm: String(p.comments || 0) })
    setSaveError('')
  }

  const save = async () => {
    if (!sheetPost) return
    setSaving(true)
    setSaveError('')
    try {
      await api('/dashboard/posts/metrics', {
        method: 'POST',
        body: JSON.stringify({
          post_id: sheetPost.id,
          impressions: Number(draft.imp) || 0,
          reactions: Number(draft.rx) || 0,
          comments: Number(draft.cm) || 0,
        }),
      })
      setSheetPost(null)
      refresh()
    } catch (e: any) {
      setSaveError(e?.message || 'Could not save metrics.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Screen refreshing={refreshing} onRefresh={refresh}>
      <ScreenTitle sub={data ? `${data.total} logged` : undefined}>Posts</ScreenTitle>

      {loading && !data ? <LoadingState /> : null}
      {error && !data ? <ErrorState message={error} onRetry={refresh} /> : null}

      {data ? (
        <>
          <View style={styles.statsRow}>
            <StatTile value={fmtK(data.total_impressions)} label="Impressions" />
            <StatTile value={fmtK(data.total_reactions)} label="Reactions" />
            <StatTile value={fmtK(data.total_comments)} label="Comments" accent />
          </View>

          {data.posts.length === 0 ? (
            <EmptyState
              message="No posts logged yet."
              suggestions={['Import your LinkedIn CSV from the desktop app', 'Posting after interviews tends to earn the most engagement']}
            />
          ) : (
            data.posts.map((p) => (
              <PressableScale key={p.id} onPress={() => nav.navigate('PostDetail', { post: p })}>
                <Card raised style={{ marginTop: 10 }}>
                  <Text style={styles.postText} numberOfLines={4}>
                    {p.text}
                  </Text>
                  {p.hashtags && p.hashtags.length > 0 ? (
                    <Text style={styles.tags} numberOfLines={1}>
                      {p.hashtags.map((h) => (h.startsWith('#') ? h : `#${h}`)).join(' ')}
                    </Text>
                  ) : p.posted_date ? (
                    <Text style={styles.tags}>{p.posted_date.slice(0, 10)}</Text>
                  ) : null}
                  <View style={styles.metricsRow}>
                    <View style={styles.metrics}>
                      <Text style={styles.metric}>◎ {fmtK(p.impressions)}</Text>
                      <Text style={styles.metric}>♥ {fmtK(p.reactions)}</Text>
                      <Text style={styles.metric}>💬 {fmtK(p.comments)}</Text>
                    </View>
                    <Pressable style={styles.updateBtn} onPress={() => openSheet(p)}>
                      <Text style={styles.updateText}>Update</Text>
                    </Pressable>
                  </View>
                </Card>
              </PressableScale>
            ))
          )}
        </>
      ) : null}

      {/* Update metrics bottom sheet */}
      <Modal visible={sheetPost !== null} transparent animationType="slide" onRequestClose={() => setSheetPost(null)}>
        <Pressable style={styles.backdrop} onPress={() => setSheetPost(null)}>
          <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : undefined} style={{ width: '100%' }}>
            <Pressable style={styles.sheet} onPress={() => {}}>
              <View style={styles.grabber} />
              <View style={styles.sheetHeader}>
                <Text style={styles.sheetTitle}>Update metrics</Text>
                <Pressable onPress={() => setSheetPost(null)} hitSlop={10}>
                  <Text style={styles.sheetClose}>×</Text>
                </Pressable>
              </View>
              <Text style={styles.sheetText} numberOfLines={2}>
                {sheetPost?.text}
              </Text>
              <Text style={styles.fieldLabel}>IMPRESSIONS</Text>
              <TextInput
                style={styles.input}
                value={draft.imp}
                onChangeText={(v) => setDraft((d) => ({ ...d, imp: digitsOnly(v) }))}
                keyboardType="number-pad"
              />
              <View style={styles.fieldRow}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.fieldLabel}>REACTIONS</Text>
                  <TextInput
                    style={styles.input}
                    value={draft.rx}
                    onChangeText={(v) => setDraft((d) => ({ ...d, rx: digitsOnly(v) }))}
                    keyboardType="number-pad"
                  />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.fieldLabel}>COMMENTS</Text>
                  <TextInput
                    style={styles.input}
                    value={draft.cm}
                    onChangeText={(v) => setDraft((d) => ({ ...d, cm: digitsOnly(v) }))}
                    keyboardType="number-pad"
                  />
                </View>
              </View>
              {saveError ? <Text style={styles.saveError}>{saveError}</Text> : null}
              <Pressable style={[styles.saveBtn, saving && { opacity: 0.6 }]} onPress={save} disabled={saving}>
                <Text style={styles.saveBtnText}>{saving ? 'Saving…' : 'Save metrics'}</Text>
              </Pressable>
            </Pressable>
          </KeyboardAvoidingView>
        </Pressable>
      </Modal>
    </Screen>
  )
}

const styles = StyleSheet.create({
  statsRow: { flexDirection: 'row', gap: 10, marginTop: 16 },
  postText: { fontSize: 14, color: t.textBright, lineHeight: 19.5 },
  tags: { marginTop: 10, fontSize: 12, color: t.cyanBright, fontFamily: fonts.mono },
  metricsRow: { marginTop: 12, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  metrics: { flexDirection: 'row', gap: 16 },
  metric: { fontSize: 12, color: t.muted, fontFamily: fonts.mono },
  updateBtn: {
    backgroundColor: 'rgba(0,181,200,.12)',
    borderColor: t.tintBorder,
    borderWidth: 1,
    borderRadius: 9,
    paddingHorizontal: 11,
    paddingVertical: 5,
  },
  updateText: { fontSize: 11.5, fontWeight: '600', color: t.cyanBright },
  backdrop: { flex: 1, backgroundColor: 'rgba(4,7,14,.62)', justifyContent: 'flex-end' },
  sheet: {
    width: '100%',
    backgroundColor: t.sheet,
    borderTopLeftRadius: 26,
    borderTopRightRadius: 26,
    borderTopWidth: 1,
    borderColor: 'rgba(255,255,255,.1)',
    paddingTop: 14,
    paddingHorizontal: 20,
    paddingBottom: 40,
  },
  grabber: { width: 38, height: 4, borderRadius: 999, backgroundColor: 'rgba(255,255,255,.18)', alignSelf: 'center', marginBottom: 16 },
  sheetHeader: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  sheetTitle: { fontSize: 18, fontWeight: '700', color: t.text },
  sheetClose: { color: t.muted, fontSize: 24, lineHeight: 24 },
  sheetText: { marginTop: 6, fontSize: 12.5, color: t.muted, lineHeight: 17.5 },
  fieldLabel: {
    marginTop: 16,
    fontSize: 11,
    fontWeight: '600',
    letterSpacing: 1,
    color: t.muted2,
    fontFamily: fonts.mono,
  },
  input: {
    marginTop: 6,
    backgroundColor: 'rgba(255,255,255,.05)',
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,.12)',
    borderRadius: 12,
    paddingHorizontal: 13,
    paddingVertical: 11,
    color: t.text,
    fontSize: 15,
  },
  fieldRow: { flexDirection: 'row', gap: 12 },
  saveError: { marginTop: 12, color: t.red, fontSize: 12.5 },
  saveBtn: { marginTop: 20, backgroundColor: t.cyan, borderRadius: 14, paddingVertical: 13, alignItems: 'center' },
  saveBtnText: { color: t.cyanInk, fontWeight: '700', fontSize: 15 },
})
