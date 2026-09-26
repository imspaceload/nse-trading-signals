'use client';
import { useState } from 'react';
import { api } from '../../lib/api';
import { fmtTime } from '../../lib/format';
import { usePolling } from '../../hooks/usePolling';
import type { LogKind } from '../../lib/types';
import { Btn, Empty, ErrorBox, SkeletonRows, Updated } from '../ui';

const KINDS: LogKind[] = ['ENTERED', 'EXIT', 'AVERAGED', 'SKIP', 'FAILED', 'ERROR'];
const COLOR: Record<LogKind, string> = {
  ENTERED: 'text-up', EXIT: 'text-accent-soft', AVERAGED: 'text-warn', SKIP: 'text-dim', FAILED: 'text-down', ERROR: 'text-down',
};

export function AutoTradeLogTab({ active, marketOpen }: { active: boolean; marketOpen: boolean }) {
  const [shown, setShown] = useState<LogKind[]>(KINDS);
  const kindsKey = shown.join(',');

  const { data, error, loading, refreshing, updatedAt, refresh } = usePolling(
    signal => api.getAutoLogs(shown.length === KINDS.length ? [] : shown, 300, signal),
    { intervalMs: marketOpen ? 5000 : 30000, enabled: active && shown.length > 0, resetKey: kindsKey },
  );

  const toggle = (k: LogKind) => setShown(prev => (prev.includes(k) ? prev.filter(x => x !== k) : [...prev, k]));

  return (
    <div className="p-3">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        {KINDS.map(k => (
          <button
            key={k}
            type="button"
            aria-pressed={shown.includes(k)}
            onClick={() => toggle(k)}
            className={`rounded-full border px-2.5 py-1 text-[11px] font-bold transition-opacity ${COLOR[k]} ${
              shown.includes(k) ? 'border-current bg-white/5' : 'border-line opacity-40'
            }`}
          >
            {k}
          </button>
        ))}
        <Btn small onClick={() => setShown(KINDS)} disabled={shown.length === KINDS.length}>All</Btn>
        <Btn small tone="primary" onClick={refresh} disabled={refreshing}>{refreshing ? 'Refreshing…' : '🔄 Refresh'}</Btn>
        <Updated at={updatedAt} />
      </div>

      {error && <div className="mb-3"><ErrorBox message={error.message} onRetry={refresh} stale={!!data} /></div>}
      {shown.length === 0 && <Empty>Pick at least one event type.</Empty>}
      {shown.length > 0 && loading && <SkeletonRows rows={10} />}

      {data && data.length > 0 && (
        <>
          <p className="mb-1.5 text-[11px] text-muted">Latest {data.length} events, newest first.</p>
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-xs">
              <tbody>
                {data.map((r, i) => (
                  <tr key={`${r.id ?? r.at}-${i}`} className="border-b border-line/30 align-top">
                    <td className="whitespace-nowrap px-2 py-1.5 text-muted">{fmtTime(r.at)}</td>
                    <td className={`px-2 py-1.5 font-bold ${COLOR[r.kind] ?? 'text-dim'}`}>{r.kind}</td>
                    <td className="px-2 py-1.5 font-semibold">{r.symbol}</td>
                    <td className="px-2 py-1.5 text-dim">{r.message}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
      {data && data.length === 0 && shown.length > 0 && !error && (
        <Empty>No activity yet. Events appear here once the worker runs during market hours.</Empty>
      )}
    </div>
  );
}
