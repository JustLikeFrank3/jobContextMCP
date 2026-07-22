// Fetch lifecycle for the cross-domain dataset bundle (lib/store). Same
// shape as useDashData but plumbs the force flag through so pull-to-refresh
// punches past the store's 60s cache while focus-refetches ride it.
import { useFocusEffect } from '@react-navigation/native'
import { useCallback, useRef, useState } from 'react'
import { Datasets, loadDatasets } from '../lib/store'

export function useDatasets() {
  const [data, setData] = useState<Datasets | null>(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState('')
  const seq = useRef(0)

  const load = useCallback(async (force = false) => {
    const mySeq = ++seq.current
    if (force) setRefreshing(true)
    try {
      const result = await loadDatasets(force)
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
  }, [])

  useFocusEffect(
    useCallback(() => {
      load()
    }, [load]),
  )

  const refresh = useCallback(() => load(true), [load])
  return { data, loading, refreshing, error, refresh }
}
