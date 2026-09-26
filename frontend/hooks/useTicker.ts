'use client';
import { useEffect, useRef, useState } from 'react';
import type { Quote } from '../lib/types';

export type { Quote as QuoteData };

// Empty string / unset both fall back to same-origin (nginx proxies /ws) in production.
function wsBase(): string {
  const env = process.env.NEXT_PUBLIC_WS_URL;
  if (env) return env;
  if (typeof window === 'undefined') return 'ws://localhost:8000';
  const api = process.env.NEXT_PUBLIC_API_URL;
  if (api === undefined) return 'ws://localhost:8000';
  return `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}`;
}

export type TickerStatus = 'connecting' | 'live' | 'reconnecting';

/**
 * Live quotes over one WebSocket. Reconnects with exponential backoff (1s → 30s), ignores
 * events from sockets that were replaced, and debounces symbol changes so editing the
 * watchlist doesn't open a new socket per keystroke.
 */
export function useTicker(symbols: string[]) {
  const [quotes, setQuotes] = useState<Record<string, Quote>>({});
  const [status, setStatus] = useState<TickerStatus>('connecting');
  const symbolsKey = [...new Set(symbols)].sort().join(',');
  const attempts = useRef(0);

  useEffect(() => {
    let closedByUs = false;
    let ws: WebSocket | null = null;
    let retryTimer: ReturnType<typeof setTimeout> | undefined;

    const connect = () => {
      const socket = new WebSocket(`${wsBase()}/ws/ticker${symbolsKey ? `?symbols=${encodeURIComponent(symbolsKey)}` : ''}`);
      ws = socket;

      socket.onopen = () => { attempts.current = 0; setStatus('live'); };
      socket.onmessage = e => {
        if (ws !== socket) return;
        try {
          const data = JSON.parse(e.data) as Record<string, Quote>;
          setQuotes(prev => ({ ...prev, ...data }));
        } catch { /* ignore malformed frame */ }
      };
      socket.onclose = () => {
        if (closedByUs || ws !== socket) return;
        setStatus('reconnecting');
        attempts.current += 1;
        retryTimer = setTimeout(connect, Math.min(1000 * 2 ** (attempts.current - 1), 30000));
      };
      socket.onerror = () => socket.close();
    };

    const startTimer = setTimeout(connect, 400); // debounce rapid symbol changes
    return () => {
      closedByUs = true;
      clearTimeout(startTimer);
      clearTimeout(retryTimer);
      ws?.close();
    };
  }, [symbolsKey]);

  return { quotes, status };
}
