'use client';
import { useState } from 'react';
import { TIMEFRAMES, TV_INTERVAL, toTvSymbol } from '../../lib/constants';
import { fmtPct, fmtPrice, pnlClass } from '../../lib/format';
import type { Quote } from '../../lib/types';
import { Segmented, Skeleton } from '../ui';

export function ChartTab({ symbol, quote, tf, onTf }: {
  symbol: string; quote?: Quote; tf: string; onTf: (tf: string) => void;
}) {
  const [loaded, setLoaded] = useState<string | null>(null);
  const frameKey = `${symbol}|${tf}`;

  return (
    <div className="flex h-full flex-col">
      <div className="flex shrink-0 items-center justify-between border-b border-line px-3 py-2">
        <div className="flex items-baseline gap-3">
          <span className="text-lg font-bold">{symbol}</span>
          <span className="text-[10px] text-muted">NSE</span>
          {quote && (
            <>
              <span className="text-lg font-bold">₹{fmtPrice(quote.ltp)}</span>
              <span className={`text-sm font-semibold ${pnlClass(quote.pct)}`}>
                {quote.pct >= 0 ? '▲' : '▼'} {fmtPct(Math.abs(quote.pct), false)}
              </span>
            </>
          )}
        </div>
        <Segmented options={TIMEFRAMES} value={tf as (typeof TIMEFRAMES)[number]} onChange={onTf} />
      </div>

      <div className="relative min-h-[500px] flex-1">
        {loaded !== frameKey && <Skeleton className="absolute inset-2" />}
        {/* key = remount only when the symbol/timeframe changes, never on a data refresh */}
        <iframe
          key={frameKey}
          title={`${symbol} chart`}
          onLoad={() => setLoaded(frameKey)}
          loading="lazy"
          src={`https://s.tradingview.com/widgetembed/?symbol=${encodeURIComponent(toTvSymbol(symbol))}&interval=${TV_INTERVAL[tf] ?? '5'}&theme=dark&style=1&locale=en&toolbar_bg=%230a0a14&enable_publishing=0&hide_top_toolbar=0&hide_legend=0&save_image=0&hide_side_toolbar=0`}
          className="absolute inset-0 h-full w-full border-0"
          allowFullScreen
        />
      </div>
    </div>
  );
}
