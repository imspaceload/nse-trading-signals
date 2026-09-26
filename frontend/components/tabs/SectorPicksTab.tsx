'use client';
import { api } from '../../lib/api';
import { SCAN_TIMEFRAMES, SECTORS } from '../../lib/constants';
import { fmtPct, fmtPrice, pnlClass } from '../../lib/format';
import { usePolling } from '../../hooks/usePolling';
import { Btn, DirBadge, Empty, ErrorBox, ScoreBars, Segmented, SkeletonRows, Updated } from '../ui';

const sigColor = (v: string) => (v === 'BUY' ? 'text-up' : v === 'SELL' ? 'text-down' : 'text-dim');

export function SectorPicksTab({ sector, onSector, tf, onTf, onPick, active }: {
  sector: string; onSector: (s: string) => void; tf: string; onTf: (t: string) => void;
  onPick: (sym: string) => void; active: boolean;
}) {
  const { data, error, loading, refreshing, updatedAt, refresh } = usePolling(
    signal => api.getSectorPicks(sector, tf, signal),
    { intervalMs: 60000, enabled: active, resetKey: `${sector}|${tf}` },
  );

  return (
    <div className="p-3">
      <div className="mb-4 flex flex-wrap items-center gap-2.5">
        <select
          value={sector}
          onChange={e => onSector(e.target.value)}
          aria-label="Sector"
          className="rounded-md border border-line bg-card px-2.5 py-1.5 text-sm outline-none focus:border-accent"
        >
          {SECTORS.map(s => <option key={s} value={s}>{s}</option>)}
        </select>
        <Segmented options={SCAN_TIMEFRAMES} value={tf as (typeof SCAN_TIMEFRAMES)[number]} onChange={onTf} />
        <Btn tone="primary" onClick={refresh} disabled={refreshing}>{refreshing ? 'Loading…' : '⟳ Refresh'}</Btn>
        <Updated at={updatedAt} />
      </div>

      {error && <div className="mb-3"><ErrorBox message={error.message} onRetry={refresh} stale={!!data} /></div>}
      {loading && <SkeletonRows rows={4} />}

      {data && data.length > 0 && (
        <div className="grid grid-cols-[repeat(auto-fill,minmax(260px,1fr))] gap-3">
          {data.slice(0, 4).map(s => (
            <button
              key={s.symbol}
              type="button"
              onClick={() => onPick(s.symbol)}
              className={`rounded-lg border bg-[#0f0f1e] p-3.5 text-left transition-colors hover:bg-[#13132a] ${
                s.direction === 'BUY' ? 'border-[#1e4d1e]' : s.direction === 'SELL' ? 'border-[#4d1e1e]' : 'border-line'
              }`}
            >
              <div className="mb-2.5 flex items-start justify-between">
                <div>
                  <div className="font-bold">{s.symbol}</div>
                  <div className="text-[11px] text-dim">NSE · F&amp;O</div>
                </div>
                <DirBadge dir={s.direction} />
              </div>
              <div className="mb-2 flex justify-between">
                <div>
                  <div className="text-[10px] uppercase text-muted">Price</div>
                  <div className="font-bold">₹{fmtPrice(s.spot)}</div>
                </div>
                <div className="text-right">
                  <div className="text-[10px] uppercase text-muted">Day change</div>
                  <div className={`font-bold ${pnlClass(s.day_pct)}`}>{fmtPct(s.day_pct)}</div>
                </div>
              </div>
              <div className="mb-2"><ScoreBars score={s.score} dir={s.direction} thick /></div>
              <div className="flex flex-wrap gap-2 text-[11px] text-muted">
                <span>RSI <b className={s.rsi < 40 ? 'text-up' : s.rsi > 60 ? 'text-down' : 'text-dim'}>{s.rsi.toFixed(0)}</b></span>
                <span>MACD <b className={sigColor(s.macd)}>{s.macd}</b></span>
                <span>ST <b className={s.supertrend === 'BULL' ? 'text-up' : 'text-down'}>{s.supertrend}</b></span>
                <span>VWAP <b className={sigColor(s.vwap)}>{s.vwap}</b></span>
                {s.vol_spike && <span className="text-warn">VOL SPIKE</span>}
              </div>
            </button>
          ))}
        </div>
      )}
      {data && data.length === 0 && !error && <Empty>No picks for this sector right now.</Empty>}
    </div>
  );
}
