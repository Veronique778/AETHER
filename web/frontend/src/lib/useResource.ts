import { useCallback, useEffect, useRef, useState } from 'react';

export type Resource<T> = {
  data: T | undefined;
  error: Error | undefined;
  loading: boolean;
  reload: () => void;
};

/**
 * Small data-fetching hook (loading / error / data / reload) with stale-response
 * protection. `key` must change whenever the request changes.
 * Swap for TanStack Query later without touching components that use `Resource<T>`.
 */
export function useResource<T>(key: string | null, fetcher: () => Promise<T>): Resource<T> {
  const [state, setState] = useState<{ data?: T; error?: Error; loading: boolean }>({ loading: key != null });
  const [tick, setTick] = useState(0);
  const fetchRef = useRef(fetcher);
  fetchRef.current = fetcher;
  useEffect(() => {
    if (key == null) { setState({ loading: false }); return; }
    let alive = true;
    setState((s) => ({ data: s.data, loading: true }));
    fetchRef.current().then(
      (data) => { if (alive) setState({ data, loading: false }); },
      (error: unknown) => { if (alive) setState({ error: error instanceof Error ? error : new Error(String(error)), loading: false }); },
    );
    return () => { alive = false; };
  }, [key, tick]);
  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { data: state.data, error: state.error, loading: state.loading, reload };
}
