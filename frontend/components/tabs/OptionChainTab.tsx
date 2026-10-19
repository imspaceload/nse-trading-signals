'use client';
import { useMemo, useState } from 'react';
import { api } from '../../lib/api';
import { fmtInt } from '../../lib/format';
import { usePolling } from '../../hooks/usePolling';
import type { OptionRow } from '../../lib/types';
import { SymbolPicker } from '../SymbolPicker';
import { Btn, Empty, ErrorBox, SkeletonRows, Updated } from '../ui';

const atmOf = (spot: number) => (spot <= 0 ? 0 : spot < 5000 ? Math.round(spot / 50) * 50 : Math.round(spot / 100) * 100);
const k = (n?: number) => (n ? `${(n / 1000).toFixed(0)}K` : '--');

export function OptionChainTab({ symbol, onSymbol, marketOpen, active }: {
  symbol: string; onSymbol: (s: string) => void; marketOpen: boolean; active: boolean;
}) {
  const [expiry, setExpiry] = useState<string>('');
  const fo = usePolling(signal => api.getFoSymbols(signal), { intervalMs: null, enabled: active });

  const { data, error, loading, refreshing, updatedAt, refresh } = usePolling(
    signal => api.getOptionChain(symbol, signal),
    { intervalMs: marketOpen ? 30000 : null, enabled: active, resetKey: symbol },
  );

  const records = data?.records;
  const spot = records?.underlyingValue ?? 0;
  const atm = atmOf(spot);
  const expiries = useMemo(() => records?.expiryDates ?? [], [records]);
  const activeExpiry = expiry && expiries.includes(expiry) ? expiry : expiries[0] ?? '';

  const rows: OptionRow[] = useMemo(() => {
    const all = (records?.data ?? []).filter(r => (r.CE || r.PE) && (!r.expiryDate || !activeExpiry || r.expiryDate.toUpperCase() === activeExpiry.toUpperCase()));
    if (!all.length) return [];
    const i = all.findIndex(r => r.strikePrice >= atm);
    const mid = i < 0 ? all.length - 1 : i;
    return all.slice(Math.max(0, mid - 8), mid + 9);
  }, [records, activeExpiry, atm]);

  return (
    <div className="p-3">
      <div className="mb-3 flex flex-wrap items-center gap-2.5">
        <SymbolPicker
          label="Option chain symbol"
          value={symbol}
          options={fo.data ?? []}
          loading={fo.loading}
          onPick={s => (s === symbol ? void refresh() : onSymbol(s))}
        />
        <Btn tone="primary" onClick={refresh} disabled={refreshing}>
          {refreshing ? 'Loading…' : '⟳ Refresh'}
        </Btn>
        {spot > 0 && (
          <span className="text-xs text-dim">
            Spot <b className="text-foreground">₹{fmtInt(spot)}</b> · ATM <b className="text-warn">{atm}</b>
          </span>
        )}
        {expiries.length > 0 && (
          <select
            value={activeExpiry}
            onChange={e => setExpiry(e.target.value)}
            aria-label="Expiry"
            className="rounded-md border border-line bg-card px-2 py-1.5 text-xs outline-none"
          >
            {expiries.slice(0, 8).map(x => <option key={x} value={x}>{x}</option>)}
          </select>
        )}
        <Updated at={updatedAt} refreshing={refreshing} />
      </div>

      {error && <div className="mb-3"><ErrorBox message={error.message} onRetry={refresh} stale={!!data} /></div>}
      {loading && <SkeletonRows rows={10} />}

      {rows.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-xs">
            <thead>
              <tr className="border-b border-line text-muted">
                <th className="px-2 py-1.5 text-right">CE OI</th>
                <th className="px-2 py-1.5 text-right">CE IV</th>
                <th className="px-2 py-1.5 text-right">CE LTP</th>
                <th className="px-2 py-1.5 text-center font-bold text-warn">STRIKE</th>
                <th className="px-2 py-1.5 text-left">PE LTP</th>
                <th className="px-2 py-1.5 text-left">PE IV</th>
                <th className="px-2 py-1.5 text-left">PE OI</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(r => {
                const isAtm = atm > 0 && Math.abs(r.strikePrice - atm) < 1;
                return (
                  <tr key={`${r.expiryDate ?? ''}${r.strikePrice}`} className={`border-b border-line/40 ${isAtm ? 'bg-warn/5' : ''}`}>
                    <td className="px-2 py-1 text-right text-up">{k(r.CE?.openInterest)}</td>
                    <td className="px-2 py-1 text-right text-dim">{r.CE?.impliedVolatility ? `${r.CE.impliedVolatility.toFixed(1)}%` : '--'}</td>
                    <td className="px-2 py-1 text-right font-semibold text-up">{r.CE?.lastPrice ? r.CE.lastPrice.toFixed(2) : '--'}</td>
                    <td className={`px-2.5 py-1 text-center font-bold ${isAtm ? 'text-warn' : ''}`}>
                      {r.strikePrice.toLocaleString('en-IN')}
                      {isAtm && <span className="ml-1 text-[9px]">ATM</span>}
                    </td>
                    <td className="px-2 py-1 text-left font-semibold text-down">{r.PE?.lastPrice ? r.PE.lastPrice.toFixed(2) : '--'}</td>
                    <td className="px-2 py-1 text-left text-dim">{r.PE?.impliedVolatility ? `${r.PE.impliedVolatility.toFixed(1)}%` : '--'}</td>
                    <td className="px-2 py-1 text-left text-down">{k(r.PE?.openInterest)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {!loading && !error && rows.length === 0 && <Empty>No option chain rows for {symbol}.</Empty>}
    </div>
  );
}
