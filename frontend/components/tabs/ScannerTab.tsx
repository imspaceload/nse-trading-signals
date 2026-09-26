'use client';
import { api } from '../../lib/api';
import { SCAN_TIMEFRAMES } from '../../lib/constants';
import { fmtPct, fmtPrice, pnlClass } from '../../lib/format';
import { usePolling } from '../../hooks/usePolling';
import { Btn, DirBadge, Empty, ErrorBox, ScoreBars, Segmented, SkeletonRows, Updated } from '../ui';

const sigColor = (v: string) => (v === 'BUY' ? 'text-up' : v === 'SELL' ? 'text-down' : 'text-muted');

export function ScannerTab({ tf, onTf, onPick, active }: {
  tf: string; onTf: (tf: string) => void; onPick: (sym: string) => void; active: boolean;
}) {
  const { data, error, loading, refreshing, updatedAt, refresh } = usePolling(
    signal => api.getScanner(tf, signal),
    { intervalMs: 30000, enabled: active, resetKey: tf },
  );

  return (
    <div className="p-3">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <span className="text-xs text-dim">Timeframe</span>
        <Segmented options={SCAN_TIMEFRAMES} value={tf as (typeof SCAN_TIMEFRAMES)[number]} onChange={onTf} />
        <Btn tone="primary" onClick={refresh} disabled={refreshing}>{refreshing ? '⟳ Scanning…' : '⟳ Refresh'}</Btn>
        <span className="text-[10px] text-muted">Auto-refresh every 30s</span>
        <Updated at={updatedAt} />
      </div>

      {error && <div className="mb-3"><ErrorBox message={error.message} onRetry={refresh} stale={!!data} /></div>}
      {loading && (
        <>
          <p className="mb-2 text-xs text-muted">Scanning stocks across all sectors… the first scan can take up to a minute.</p>
          <SkeletonRows rows={10} />
        </>
      )}

      {data && data.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-xs">
            <thead>
              <tr className="border-b border-line text-muted">
                {['#', 'Symbol', 'Price', 'Signal', 'Score', 'RSI', 'MACD', 'ST', 'VWAP', 'Day%', 'Vol'].map((h, i) => (
                  <th key={h} className={`px-2.5 py-1.5 ${i === 2 || i === 5 || i === 9 ? 'text-right' : i < 2 ? 'text-left' : 'text-center'}`}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.map((r, i) => (
                <tr
                  key={r.symbol}
                  onClick={() => onPick(r.symbol)}
                  className={`cursor-pointer border-b border-line/30 hover:bg-white/[0.03] ${r.direction === 'BUY' ? 'bg-up/[0.03]' : r.direction === 'SELL' ? 'bg-down/[0.03]' : ''}`}
                >
                  <td className="px-2.5 py-1.5 text-muted">{i + 1}</td>
                  <td className="px-2.5 py-1.5 font-semibold">{r.symbol}</td>
                  <td className="px-2.5 py-1.5 text-right">₹{fmtPrice(r.spot)}</td>
                  <td className="px-2.5 py-1.5 text-center"><DirBadge dir={r.direction} /></td>
                  <td className="px-2.5 py-1.5 text-center"><ScoreBars score={r.score} dir={r.direction} /></td>
                  <td className={`px-2.5 py-1.5 text-right ${r.rsi < 40 ? 'text-up' : r.rsi > 60 ? 'text-down' : 'text-dim'}`}>{r.rsi.toFixed(1)}</td>
                  <td className={`px-2.5 py-1.5 text-center ${sigColor(r.macd)}`}>{r.macd}</td>
                  <td className={`px-2.5 py-1.5 text-center font-semibold ${r.supertrend === 'BULL' ? 'text-up' : 'text-down'}`}>
                    {r.supertrend === 'BULL' ? '▲ BULL' : '▼ BEAR'}
                  </td>
                  <td className={`px-2.5 py-1.5 text-center ${sigColor(r.vwap)}`}>{r.vwap}</td>
                  <td className={`px-2.5 py-1.5 text-right ${pnlClass(r.day_pct)}`}>{fmtPct(r.day_pct)}</td>
                  <td className={`px-2.5 py-1.5 text-center ${r.vol_spike ? 'text-warn' : 'text-muted'}`}>{r.vol_spike ? 'SPIKE' : '--'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {data && data.length === 0 && !error && <Empty>The scan returned no stocks. Try again in a moment.</Empty>}
    </div>
  );
}
