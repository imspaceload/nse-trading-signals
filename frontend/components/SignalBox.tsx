'use client';
import type { ReactNode } from 'react';
import { fmtLevel } from '../lib/format';
import type { ChartSignal } from '../lib/types';

const lv = (n: number) => `₹${fmtLevel(n)}`;
const strike = (n: number) => n.toLocaleString('en-IN', { maximumFractionDigits: 2 });

const TONE = {
  BUY: { box: 'border-[#1e4d1e] border-l-up bg-[#0b1a0b]', label: 'text-up', head: '▲ BUY' },
  SELL: { box: 'border-[#4d1e1e] border-l-down bg-[#1a0b0b]', label: 'text-down', head: '▼ SELL' },
  NEUTRAL: { box: 'border-line border-l-dim bg-card', label: 'text-dim', head: '⏸ NEUTRAL' },
} as const;

const sig = (v: string) => (v === 'BUY' || v === 'BULL' ? 'text-up' : v === 'SELL' || v === 'BEAR' ? 'text-down' : 'text-muted');

function Level({ label, value, className }: { label: string; value: number | null; className: string }) {
  if (!value) return null;
  return (
    <div className="min-w-0 rounded-md border border-white/10 bg-white/[0.04] px-1 py-1 text-center sm:min-w-[68px] sm:px-2.5">
      <div className="text-[9px] uppercase tracking-wide text-muted">{label}</div>
      <div className={`truncate text-xs font-bold sm:text-sm ${className}`}>{lv(value)}</div>
    </div>
  );
}

/** What the auto-trader sees for this symbol (15m score) and the previous-session pivot plan. */
export function SignalBox({ s }: { s: ChartSignal }) {
  const tone = TONE[s.direction];
  const o = s.option;
  const { levels: L, auto_trader: at } = s;

  let plan: ReactNode;
  if (s.direction === 'NEUTRAL') {
    plan = o ? (
      <>
        <b>{o.underlying}</b> ·{' '}
        <span className="text-up">Break {lv(o.ce_trigger)} → {strike(o.ce_strike)} CE</span>
        <span className="mx-2 text-muted">|</span>
        <span className="text-down">Break {lv(o.pe_trigger)} → {strike(o.pe_strike)} PE</span>
      </>
    ) : (
      <>
        <b>{s.symbol}</b> · <span className="text-up">Buy above {lv(s.pivots.R1)}</span>
        <span className="mx-2 text-muted">|</span>
        <span className="text-down">Sell below {lv(s.pivots.S1)}</span>
      </>
    );
  } else if (o) {
    // Bearish = buy a put (the auto-trader never writes options).
    const side = s.direction === 'BUY' ? 'CE' : 'PE';
    plan = <>BUY <b>{o.underlying} {strike(o.atm)} {side}</b> <span className="text-xs text-muted">@ spot {lv(s.spot)} · ATM {side === 'CE' ? 'call' : 'put'}</span></>;
  } else {
    plan = <>{s.direction === 'BUY' ? 'Buy' : 'Sell'} <b>{s.symbol}</b> @ {lv(s.spot)}</>;
  }

  const meetsScore = s.direction !== 'NEUTRAL' && s.score >= at.min_score;

  return (
    <div className={`mx-2 mt-2 rounded-lg border border-l-[3px] px-3 py-2 ${tone.box}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <div className={`text-[11px] font-extrabold tracking-wider ${tone.label}`}>{tone.head}</div>
          <div className="mt-0.5 text-[15px] font-semibold">{plan}</div>
          <div className="mt-0.5 text-[11px] text-muted">
            Target avg {lv(L.AVG)} · PP {lv(s.pivots.PP)}
          </div>
        </div>
        <div className="grid w-full grid-cols-5 gap-1 sm:flex sm:w-auto sm:flex-wrap sm:gap-1.5" title="Previous-session pivot levels. Chart guides only: the auto-trader exits on its profit-target / stop-loss %.">
          <Level label="T1" value={L.T1} className="text-up" />
          <Level label="T2" value={L.T2} className="text-[#22c55e]" />
          <Level label="AVG" value={L.AVG} className="text-[#fbbf24]" />
          <Level label="SL1" value={L.SL1} className="text-[#f97316]" />
          <Level label="SL2" value={L.SL2} className="text-down" />
        </div>
      </div>

      <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-0.5 border-t border-white/5 pt-1.5 text-[11px] text-muted">
        <span>
          Auto-trader score <b className={meetsScore ? tone.label : 'text-dim'}>{s.score}/5</b> on {s.timeframe}
        </span>
        <span>RSI <b className={s.rsi < 40 ? 'text-up' : s.rsi > 60 ? 'text-down' : 'text-dim'}>{s.rsi.toFixed(0)}</b></span>
        <span>MACD <b className={sig(s.macd)}>{s.macd}</b></span>
        <span>ST <b className={sig(s.supertrend)}>{s.supertrend}</b></span>
        <span>VWAP <b className={sig(s.vwap)}>{s.vwap}</b></span>
        <span>Vol <b className={s.vol_spike ? 'text-warn' : 'text-muted'}>{s.vol_spike ? 'SPIKE' : '--'}</b></span>
        <span className="basis-full sm:basis-auto sm:ml-auto">
          {!at.scanned
            ? 'Not in the auto-trader’s stock list: chart guide only'
            : meetsScore
              ? `Meets the entry score (≥${at.min_score}); traded if it’s a top-4 pick in ${at.sector ?? 'its sector'}`
              : `Below the auto-trader’s entry score (needs a clear BUY/SELL with ≥${at.min_score})`}
        </span>
      </div>
    </div>
  );
}
