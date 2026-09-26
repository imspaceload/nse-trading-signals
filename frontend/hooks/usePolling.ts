'use client';
import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError } from '../lib/api';

interface Options {
  /** ms between refreshes, or null to fetch once (and on refresh()). */
  intervalMs: number | null;
  /** Set false to stop (e.g. the tab is not visible). Data stays on screen. */
  enabled?: boolean;
  /** Changing this discards the old data (a different dataset, e.g. another timeframe). */
  resetKey?: string;
}

export interface PollingResult<T> {
  data: T | undefined;
  /** Latest failure, cleared on the next success. Old `data` is kept so the screen never blanks. */
  error: ApiError | Error | null;
  /** True only for the very first load (no data yet). */
  loading: boolean;
  /** True while any request is in flight. */
  refreshing: boolean;
  /** When `data` was last fetched successfully. */
  updatedAt: number | null;
  refresh: () => Promise<void>;
}

/**
 * Poll an async fetcher with the behaviours a live dashboard needs:
 *  - never overlaps requests (waits for one to finish before scheduling the next)
 *  - pauses while the browser tab is hidden and refreshes immediately when it comes back
 *  - backs off (up to 8x) while the server is failing, instead of hammering it
 *  - aborts the request on unmount / resetKey change
 *  - keeps showing the last good data if a refresh fails
 */
export function usePolling<T>(
  fetcher: (signal: AbortSignal) => Promise<T>,
  { intervalMs, enabled = true, resetKey = '' }: Options,
): PollingResult<T> {
  const [state, setState] = useState<{ data: T | undefined; error: Error | null; updatedAt: number | null; key: string }>(
    { data: undefined, error: null, updatedAt: null, key: resetKey },
  );
  const [refreshing, setRefreshing] = useState(false);

  const fetcherRef = useRef(fetcher);
  useEffect(() => { fetcherRef.current = fetcher; });

  const runRef = useRef<() => Promise<void>>(async () => {});

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let controller: AbortController | undefined;
    let inFlight: Promise<void> | null = null;
    let failures = 0;

    const schedule = () => {
      if (cancelled || intervalMs == null) return;
      timer = setTimeout(() => { void run(); }, intervalMs * Math.min(2 ** failures, 8));
    };

    const run = (): Promise<void> => {
      if (inFlight) return inFlight;
      clearTimeout(timer);
      controller = new AbortController();
      const signal = controller.signal;
      setRefreshing(true);
      inFlight = (async () => {
        try {
          const data = await fetcherRef.current(signal);
          if (cancelled) return;
          failures = 0;
          setState({ data, error: null, updatedAt: Date.now(), key: resetKey });
        } catch (e) {
          if (cancelled || (e instanceof ApiError && e.kind === 'aborted')) return;
          failures += 1;
          setState(prev => ({ ...prev, error: e instanceof Error ? e : new Error('Request failed'), key: resetKey }));
        } finally {
          inFlight = null;
          if (!cancelled) { setRefreshing(false); schedule(); }
        }
      })();
      return inFlight;
    };
    runRef.current = run;

    const onVisibility = () => {
      if (document.hidden) {
        clearTimeout(timer);
      } else if (!inFlight) {
        void run();
      }
    };
    document.addEventListener('visibilitychange', onVisibility);

    if (!document.hidden) void run();

    return () => {
      cancelled = true;
      clearTimeout(timer);
      controller?.abort();
      document.removeEventListener('visibilitychange', onVisibility);
    };
  }, [enabled, intervalMs, resetKey]);

  const refresh = useCallback(() => runRef.current(), []);

  // Data from a different resetKey is a different dataset — never show it under the new key.
  const current = state.key === resetKey;
  const data = current ? state.data : undefined;
  const error = current ? state.error : null;
  return {
    data,
    error,
    loading: enabled && data === undefined && error === null,
    refreshing,
    updatedAt: current ? state.updatedAt : null,
    refresh,
  };
}
