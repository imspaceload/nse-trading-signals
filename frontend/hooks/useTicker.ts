'use client';
import { useEffect, useRef, useState, useCallback } from 'react';

const WS_URL = process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8000';

export interface QuoteData {
  ltp: number;
  pct: number;
  change: number;
}

export function useTicker(symbols: string[]) {
  const [quotes, setQuotes] = useState<Record<string, QuoteData>>({});
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const symbolsKey = symbols.join(',');

  const connect = useCallback(() => {
    try {
      const ws = new WebSocket(
        `${WS_URL}/ws/ticker${symbolsKey ? `?symbols=${encodeURIComponent(symbolsKey)}` : ''}`
      );
      wsRef.current = ws;

      ws.onmessage = (e) => {
        try {
          const data = JSON.parse(e.data);
          setQuotes(prev => ({ ...prev, ...data }));
        } catch {
          // ignore parse errors
        }
      };

      ws.onclose = () => {
        reconnectTimer.current = setTimeout(connect, 3000);
      };

      ws.onerror = () => {
        ws.close();
      };
    } catch {
      reconnectTimer.current = setTimeout(connect, 5000);
    }
  }, [symbolsKey]);

  useEffect(() => {
    connect();
    return () => {
      clearTimeout(reconnectTimer.current);
      wsRef.current?.close();
    };
  }, [connect]);

  return quotes;
}
