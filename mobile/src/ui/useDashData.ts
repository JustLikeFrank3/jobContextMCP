// Shared fetch lifecycle for design screens: loading → error → data, with
// pull-to-refresh and a refetch on every tab focus (a screen mounted while
// signed out must not keep a stale "Not signed in" error after sign-in).
import { useFocusEffect } from '@react-navigation/native'
import { useCallback, useRef, useState } from 'react'

export function useDashData<T>(loader: () => Promise<T>) {
  const [data, setData] = useState<T | null>(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState('')
  const seq = useRef(0)

  const load = useCallback(
    async (asRefresh = false) => {
      const mySeq = ++seq.current
      if (asRefresh) setRefreshing(true)
      try {
        const result = await loader()
        if (mySeq !== seq.current) return
        setData(result)
        setError('')
      } catch (e: any) {
        if (mySeq !== seq.current) return
        setError(e?.message || 'Something went wrong.')
      } finally {
        if (mySeq === seq.current) {
          setLoading(false)
          setRefreshing(false)
        }
      }
    },
    [loader],
  )

  useFocusEffect(
    useCallback(() => {
      load()
    }, [load]),
  )

  const refresh = useCallback(() => load(true), [load])
  return { data, loading, refreshing, error, refresh }
}
