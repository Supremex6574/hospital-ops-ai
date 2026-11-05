import { useCallback, useEffect, useRef, useState } from 'react'
import { errorMessage } from '../api/client'

/**
 * Fetch helper. While a refetch is in flight the PREVIOUS data stays in `data` (with `loading` true),
 * so charts keep their frame instead of flashing. Out-of-order responses are ignored.
 *
 *   const { data, error, loading, reload } = useApi(() => getKpis(params), [params], { enabled: ready })
 */
export function useApi(fetcher, deps, { enabled = true } = {}) {
  const [state, setState] = useState({ data: null, error: '', loading: enabled })
  const latest = useRef(0)
  const fetchRef = useRef(fetcher)
  fetchRef.current = fetcher

  const run = useCallback(() => {
    if (!enabled) return
    const id = ++latest.current
    setState((s) => ({ ...s, loading: true, error: '' }))
    fetchRef.current()
      .then((r) => { if (id === latest.current) setState({ data: r.data, error: '', loading: false }) })
      .catch((e) => { if (id === latest.current) setState((s) => ({ ...s, error: errorMessage(e, 'Could not load this data.'), loading: false })) })
  }, [enabled, ...deps]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { run() }, [run])
  return { ...state, reload: run }
}
