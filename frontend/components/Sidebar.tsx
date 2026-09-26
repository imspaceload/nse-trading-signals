'use client';
import { memo, useState } from 'react';
import type { TickerStatus } from '../hooks/useTicker';
import type { IndexQuotes, Quote } from '../lib/types';
import { fmtInt, fmtPct, fmtPrice, pnlClass } from '../lib/format';

interface Props {
  watchlist: string[];
  active: string;
  quotes: Record<string, Quote>;
  indices: IndexQuotes;
  kiteConnected: boolean;
  apiDown: boolean;
  tickerStatus: TickerStatus;
  onSelect: (s: string) => void;
  onAdd: (s: string) => void;
  onRemove: (s: string) => void;
  onConnectKite: () => void;
  /** Phone layout only: the sidebar is a drawer. Ignored from md up, where it is always shown. */
  open: boolean;
  onClose: () => void;
}

const PAGE_SIZE = 10;

const dot: Record<TickerStatus, string> = { live: 'bg-up', connecting: 'bg-warn', reconnecting: 'bg-down' };

// memo: the ticker updates `quotes` every couple of seconds; rows only re-render when their own inputs change.
const Row = memo(function Row({ sym, quote, isActive, onSelect, onRemove }: {
  sym: string; quote?: Quote; isActive: boolean; onSelect: (s: string) => void; onRemove: (s: string) => void;
}) {
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => onSelect(sym)}
      onKeyDown={e => (e.key === 'Enter' || e.key === ' ') && onSelect(sym)}
      className={`flex cursor-pointer items-center justify-between border-b border-line/35 border-l-[3px] py-2 pl-3 pr-2.5 ${
        isActive ? 'border-l-accent bg-accent/[0.07]' : 'border-l-transparent hover:bg-white/[0.02]'
      }`}
    >
      <div className="min-w-0 flex-1">
        <div className={`truncate text-[13px] font-semibold ${isActive ? 'text-accent-soft' : ''}`}>{sym}</div>
        {quote && (
          <div className={`text-[11px] ${pnlClass(quote.pct)}`}>
            {fmtPrice(quote.ltp)} <span className="ml-1">{quote.pct >= 0 ? '▲' : '▼'}{fmtPct(Math.abs(quote.pct), false)}</span>
          </div>
        )}
      </div>
      <button
        type="button"
        aria-label={`Remove ${sym}`}
        onClick={e => { e.stopPropagation(); onRemove(sym); }}
        className="px-1 text-xs text-muted hover:text-down"
      >✕</button>
    </div>
  );
});

export function Sidebar(p: Props) {
  const [input, setInput] = useState('');
  const [page, setPage] = useState(0);
  const pageCount = Math.max(1, Math.ceil(p.watchlist.length / PAGE_SIZE));
  const current = Math.min(page, pageCount - 1); // removing the last row of the last page steps back a page
  const rows = p.watchlist.slice(current * PAGE_SIZE, (current + 1) * PAGE_SIZE);

  const submit = () => {
    const s = input.trim().toUpperCase();
    if (!s) return;
    const at = p.watchlist.indexOf(s);
    p.onAdd(s);
    setPage(Math.floor((at >= 0 ? at : p.watchlist.length) / PAGE_SIZE)); // show where it landed
    setInput('');
  };

  return (
    <>
      {p.open && <button type="button" aria-label="Close watchlist" onClick={p.onClose} className="fixed inset-0 z-30 bg-black/60 md:hidden" />}
      <aside
        className={`fixed inset-y-0 left-0 z-40 flex w-[260px] flex-col overflow-hidden border-r border-line bg-panel transition-transform md:static md:z-auto md:w-[220px] md:min-w-[220px] md:translate-x-0 ${
          p.open ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        <div className="border-b border-line bg-panel-2 px-3 py-2.5">
          <div className="flex items-center justify-between gap-2">
            <span className="text-sm font-bold">Options Terminal</span>
            <span className={`rounded-full px-2 py-0.5 text-[9px] font-bold ${p.kiteConnected && !p.apiDown ? 'bg-up/15 text-up' : 'bg-down/15 text-down'}`}>
              {p.apiDown ? '● API DOWN' : p.kiteConnected ? '● LIVE' : '● OFFLINE'}
            </span>
            <button type="button" aria-label="Close watchlist" onClick={p.onClose} className="ml-auto px-1 text-muted hover:text-foreground md:hidden">✕</button>
          </div>
          {!p.kiteConnected && !p.apiDown && (
            <button
              type="button"
              onClick={p.onConnectKite}
              className="mt-1.5 w-full rounded-md border border-[#2a4a6f] bg-[#1e3a5f] px-2 py-1.5 text-[11px] font-bold text-accent-soft"
            >
              🔑 Connect Zerodha Kite
            </button>
          )}
        </div>

        <div className="border-b border-line/60 bg-[#0f0f1e] px-2 py-1.5">
          {(['NIFTY 50', 'BANK NIFTY'] as const).map(idx => {
            const q = p.quotes[idx];
            const ltp = q?.ltp ?? p.indices[idx]?.price ?? 0;
            const pct = q?.pct ?? p.indices[idx]?.pct ?? 0;
            if (!ltp) return null;
            return (
              <div key={idx} className="mb-0.5 flex justify-between text-[11px]">
                <span className="text-dim">{idx === 'NIFTY 50' ? 'NIFTY' : 'BANKNIFTY'}</span>
                <span className={`font-semibold ${pnlClass(pct)}`}>{fmtInt(ltp)} {pct >= 0 ? '▲' : '▼'}{fmtPct(Math.abs(pct), false)}</span>
              </div>
            );
          })}
        </div>

        <div className="border-b border-line/60 p-2">
          <div className="flex gap-1">
            <input
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && submit()}
              placeholder="+ Add symbol"
              aria-label="Add symbol to watchlist"
              className="min-w-0 flex-1 rounded-md border border-line bg-card px-2 py-1.5 text-xs outline-none focus:border-accent"
            />
            <button type="button" onClick={submit} aria-label="Add" className="rounded-md border border-[#2a4a6f] bg-[#1e3a5f] px-2 text-sm text-accent-soft">+</button>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto">
          <div className="flex items-center justify-between px-2 pb-0.5 pt-1 text-[9px] uppercase tracking-widest text-[#374151]">
            <span>Watchlist</span>
            <span className="flex items-center gap-1 normal-case tracking-normal text-muted" title={`Live prices: ${p.tickerStatus}`}>
              <span className={`h-1.5 w-1.5 rounded-full ${dot[p.tickerStatus]}`} />
              {p.tickerStatus}
            </span>
          </div>
          {rows.map(sym => (
            <Row key={sym} sym={sym} quote={p.quotes[sym]} isActive={sym === p.active} onSelect={p.onSelect} onRemove={p.onRemove} />
          ))}
        </div>

        {pageCount > 1 && (
          <nav aria-label="Watchlist pages" className="flex shrink-0 items-center justify-between border-t border-line bg-panel-2 px-2 py-1.5 text-[11px]">
            <button
              type="button"
              onClick={() => setPage(current - 1)}
              disabled={current === 0}
              className="rounded px-2 py-1 text-dim hover:bg-white/5 hover:text-foreground disabled:opacity-30 disabled:hover:bg-transparent"
            >‹ Prev</button>
            <span className="text-muted">
              {current * PAGE_SIZE + 1}–{current * PAGE_SIZE + rows.length} of {p.watchlist.length}
            </span>
            <button
              type="button"
              onClick={() => setPage(current + 1)}
              disabled={current >= pageCount - 1}
              className="rounded px-2 py-1 text-dim hover:bg-white/5 hover:text-foreground disabled:opacity-30 disabled:hover:bg-transparent"
            >Next ›</button>
          </nav>
        )}
      </aside>
    </>
  );
}
