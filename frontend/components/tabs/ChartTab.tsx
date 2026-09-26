'use client';
import { useEffect, useRef } from 'react';
import {
  CandlestickSeries, ColorType, CrosshairMode, HistogramSeries, LineStyle, createChart,
  type IChartApi, type IPriceLine, type ISeriesApi, type UTCTimestamp,
} from 'lightweight-charts';
import { api } from '../../lib/api';
import { TIMEFRAMES } from '../../lib/constants';
import { fmtLevel, fmtPct, fmtPrice, pnlClass } from '../../lib/format';
import { usePolling } from '../../hooks/usePolling';
import type { PivotKey, Quote } from '../../lib/types';
import { SignalBox } from '../SignalBox';
import { Empty, ErrorBox, Segmented, Skeleton, Updated } from '../ui';

// lightweight-charts renders times as UTC; shift by +5:30 so the axis reads in IST.
const IST_OFFSET = 19800;
const UP = '#4caf50';
const DOWN = '#ef4444';
const PX_PER_BAR = 8; // initial zoom: ~8px per candle keeps bodies readable on a phone and ~150 bars on desktop
const PIVOT_STYLE: Record<PivotKey, { color: string; lineStyle: LineStyle }> = {
  R2: { color: '#ef4444', lineStyle: LineStyle.Dashed },
  R1: { color: '#f97316', lineStyle: LineStyle.Dashed },
  PP: { color: '#fbbf24', lineStyle: LineStyle.Dotted },
  S1: { color: '#22c55e', lineStyle: LineStyle.Dashed },
  S2: { color: '#16a34a', lineStyle: LineStyle.Dashed },
};

// Drawn here from our own candles: TradingView's free embed widget refuses NSE symbols.
export function ChartTab({ symbol, quote, tf, onTf, marketOpen, active }: {
  symbol: string; quote?: Quote; tf: string; onTf: (tf: string) => void; marketOpen: boolean; active: boolean;
}) {
  const frameKey = `${symbol}|${tf}`;
  const { data, error, loading, refreshing, updatedAt, refresh } = usePolling(
    signal => api.getCandles(symbol, tf, signal),
    { intervalMs: marketOpen ? 15000 : null, enabled: active, resetKey: frameKey },
  );
  // Scored on the auto-trader's own 15m candles whatever timeframe is on screen.
  const { data: signal } = usePolling(
    s => api.getChartSignal(symbol, s),
    { intervalMs: marketOpen ? 30000 : null, enabled: active, resetKey: symbol },
  );

  const boxRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const volumeRef = useRef<ISeriesApi<'Histogram'> | null>(null);
  const fittedKey = useRef<string | null>(null);
  const pivotLines = useRef<IPriceLine[]>([]);
  const ltpLine = useRef<IPriceLine | null>(null);

  useEffect(() => {
    if (!boxRef.current) return;
    const chart = createChart(boxRef.current, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: 'transparent' }, textColor: '#9ca3af', attributionLogo: false },
      grid: { vertLines: { color: '#1a1a2e' }, horzLines: { color: '#1a1a2e' } },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: '#2a2a4a' },
      timeScale: { borderColor: '#2a2a4a', timeVisible: true, secondsVisible: false },
    });
    candleRef.current = chart.addSeries(CandlestickSeries, {
      upColor: UP, downColor: DOWN, borderUpColor: UP, borderDownColor: DOWN, wickUpColor: UP, wickDownColor: DOWN,
    });
    volumeRef.current = chart.addSeries(HistogramSeries, {
      priceScaleId: '', priceFormat: { type: 'volume' }, lastValueVisible: false, priceLineVisible: false,
    });
    volumeRef.current.priceScale().applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
    chartRef.current = chart;
    return () => {
      chart.remove();
      chartRef.current = candleRef.current = volumeRef.current = null;
      fittedKey.current = null;
      pivotLines.current = [];
      ltpLine.current = null;
    };
  }, []);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || !candleRef.current || !volumeRef.current) return;
    const bars = data?.candles ?? [];
    candleRef.current.setData(bars.map(c => ({
      time: (c.time + IST_OFFSET) as UTCTimestamp, open: c.open, high: c.high, low: c.low, close: c.close,
    })));
    // Indices have no volume: an all-zero histogram would only draw a stray line at 0.
    const hasVolume = bars.some(c => c.volume > 0);
    volumeRef.current.setData(!hasVolume ? [] : bars.map(c => ({
      time: (c.time + IST_OFFSET) as UTCTimestamp, value: c.volume, color: c.close >= c.open ? `${UP}55` : `${DOWN}55`,
    })));
    chart.timeScale().applyOptions({ timeVisible: tf !== '1D' });
    // Frame the latest bars once per symbol/timeframe; later refreshes keep the user's zoom and scroll.
    if (bars.length && fittedKey.current !== frameKey) {
      fittedKey.current = frameKey;
      const visible = Math.max(30, Math.round((boxRef.current?.clientWidth ?? 1200) / PX_PER_BAR));
      if (bars.length > visible) chart.timeScale().setVisibleLogicalRange({ from: bars.length - visible, to: bars.length + 3 });
      else chart.timeScale().fitContent();
    }
  }, [data, frameKey, tf]);

  useEffect(() => {
    const series = candleRef.current;
    if (!series) return;
    pivotLines.current.forEach(l => series.removePriceLine(l));
    pivotLines.current = !signal ? [] : (Object.keys(PIVOT_STYLE) as PivotKey[])
      .filter(k => signal.pivots[k] > 0)
      .map(k => series.createPriceLine({ price: signal.pivots[k], title: k, lineWidth: 1, axisLabelVisible: true, ...PIVOT_STYLE[k] }));
  }, [signal]);

  // Live tick from the ticker, between candle refreshes.
  const ltp = quote?.ltp ?? 0;
  useEffect(() => {
    const series = candleRef.current;
    if (!series) return;
    if (ltp <= 0) {
      if (ltpLine.current) series.removePriceLine(ltpLine.current);
      ltpLine.current = null;
    } else if (ltpLine.current) {
      ltpLine.current.applyOptions({ price: ltp });
    } else {
      ltpLine.current = series.createPriceLine({ price: ltp, title: 'LTP', color: '#387ed1', lineWidth: 1, lineStyle: LineStyle.Dotted, axisLabelVisible: true });
    }
  }, [ltp]);

  const empty = !loading && !error && data?.candles.length === 0;

  return (
    <div className="flex h-full flex-col">
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-2 border-b border-line px-3 py-2">
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <span className="text-lg font-bold">{symbol}</span>
          {quote && (
            <>
              <span className="text-lg font-bold">₹{fmtPrice(quote.ltp)}</span>
              <span className={`text-sm font-semibold ${pnlClass(quote.pct)}`}>
                {quote.pct >= 0 ? '▲' : '▼'} {fmtPct(Math.abs(quote.pct), false)}
              </span>
            </>
          )}
          {data && (
            <span
              className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${data.source === 'kite' ? 'bg-up/15 text-up' : 'bg-warn/15 text-warn'}`}
              title={data.source === 'kite' ? 'Candles from Zerodha Kite' : 'Candles from Yahoo Finance (about 15 minutes delayed)'}
            >
              {data.source === 'kite' ? 'Kite' : 'Yahoo · delayed'}
            </span>
          )}
          {signal && (
            <span className="text-[11px] text-muted">
              O {fmtLevel(signal.session.open)} · H {fmtLevel(signal.session.high)} · L {fmtLevel(signal.session.low)}
            </span>
          )}
          <Updated at={updatedAt} refreshing={refreshing} />
        </div>
        <Segmented options={TIMEFRAMES} value={tf as (typeof TIMEFRAMES)[number]} onChange={onTf} />
      </div>

      {signal && <div className="shrink-0"><SignalBox s={signal} /></div>}

      {error && <div className="shrink-0 px-3 pt-2"><ErrorBox message={error.message} onRetry={refresh} stale={!!data} /></div>}

      <div className="relative min-h-[320px] flex-1">
        <div ref={boxRef} className="absolute inset-0" />
        {loading && <Skeleton className="absolute inset-2" />}
        {empty && <div className="absolute inset-0 flex items-center justify-center"><Empty>No candles for {symbol} on {tf}.</Empty></div>}
      </div>
    </div>
  );
}
