'use client';
import { useEffect, useRef, useState } from 'react';
import { api, errorMessage } from '../../lib/api';
import { ago, fmtInt, fmtPct, fmtPrice, fmtRupee, fmtSigned, fmtTime, pnlClass } from '../../lib/format';
import { usePolling } from '../../hooks/usePolling';
import type { AutoPosition, AutoTraderConfig, AutoTraderState } from '../../lib/types';
import { Btn, Card, DirBadge, Empty, ErrorBox, SkeletonRows, Stat, Updated } from '../ui';
import { useToast } from '../Toast';

// ── Config form definition ──────────────────────────────────────────────────

type NumKey = 'total_capital' | 'max_margin_pct' | 'max_active_trades' | 'max_trades_per_day' | 'profit_target_pct'
  | 'averaging_drop_pct' | 'max_averaging_rounds' | 'stop_loss_pct' | 'min_entry_score';

const NUM_FIELDS: { key: NumKey; label: string; hint?: string; min: number; max: number; step: number; int?: boolean }[] = [
  { key: 'total_capital', label: 'Total capital (₹)', min: 100, max: 1e9, step: 1000 },
  { key: 'max_margin_pct', label: 'Max margin per trade (%)', hint: 'Cap per trade = capital × this %', min: 1, max: 100, step: 1 },
  { key: 'max_active_trades', label: 'Max active trades', hint: 'Open at the same time', min: 1, max: 10, step: 1, int: true },
  { key: 'max_trades_per_day', label: 'Max trades per day', hint: '0 = unlimited', min: 0, max: 50, step: 1, int: true },
  { key: 'profit_target_pct', label: 'Profit target (%)', min: 0.5, max: 100, step: 0.5 },
  { key: 'stop_loss_pct', label: 'Stop-loss (%)', hint: '0 = off', min: 0, max: 90, step: 0.5 },
  { key: 'averaging_drop_pct', label: 'Averaging trigger drop (%)', min: 0.5, max: 50, step: 0.5 },
  { key: 'max_averaging_rounds', label: 'Max averaging rounds', min: 0, max: 10, step: 1, int: true },
  { key: 'min_entry_score', label: 'Min signal score (of 5)', min: 1, max: 5, step: 1, int: true },
];

type Draft = Partial<Record<NumKey | 'trade_mode' | 'stop_loss_action', string>>;

function buildChanges(cfg: AutoTraderConfig, draft: Draft): { changes: Partial<AutoTraderConfig>; problem: string | null } {
  const changes: Record<string, number | string> = {};
  for (const f of NUM_FIELDS) {
    const raw = draft[f.key];
    if (raw === undefined) continue;
    const n = Number(raw);
    if (raw.trim() === '' || !Number.isFinite(n)) return { changes: {}, problem: `${f.label}: enter a number` };
    if (f.int && !Number.isInteger(n)) return { changes: {}, problem: `${f.label}: must be a whole number` };
    if (n < f.min || n > f.max) return { changes: {}, problem: `${f.label}: must be between ${f.min} and ${f.max}` };
    if (n !== cfg[f.key]) changes[f.key] = n;
  }
  if (draft.trade_mode !== undefined && draft.trade_mode !== cfg.trade_mode) changes.trade_mode = draft.trade_mode;
  if (draft.stop_loss_action !== undefined && draft.stop_loss_action !== cfg.stop_loss_action) changes.stop_loss_action = draft.stop_loss_action;
  return { changes: changes as Partial<AutoTraderConfig>, problem: null };
}

// ── Small pieces ────────────────────────────────────────────────────────────

/** Two-step destructive button: first click arms it, second click within 4s confirms. */
function ConfirmBtn({ label, confirmLabel, onConfirm, busy }: {
  label: string; confirmLabel: string; onConfirm: () => void; busy?: boolean;
}) {
  const [armed, setArmed] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => () => clearTimeout(timer.current), []);
  return (
    <Btn
      small
      tone={armed ? 'danger' : 'neutral'}
      disabled={busy}
      onClick={() => {
        if (!armed) {
          setArmed(true);
          timer.current = setTimeout(() => setArmed(false), 4000);
        } else {
          clearTimeout(timer.current);
          setArmed(false);
          onConfirm();
        }
      }}
    >
      {busy ? 'Working…' : armed ? confirmLabel : label}
    </Btn>
  );
}

function StatusPill({ ok, text }: { ok: boolean; text: string }) {
  return (
    <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${ok ? 'bg-up/15 text-up' : 'bg-down/15 text-down'}`}>● {text}</span>
  );
}

// ── Tab ─────────────────────────────────────────────────────────────────────

export function AutoTraderTab({ active, marketOpen }: { active: boolean; marketOpen: boolean }) {
  const toast = useToast();
  const { data, error, loading, refreshing, updatedAt, refresh } = usePolling(
    signal => api.getAutoState(signal),
    { intervalMs: marketOpen ? 5000 : 30000, enabled: active },
  );

  const [draft, setDraft] = useState<Draft | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [showWatch, setShowWatch] = useState(false);

  const watch = usePolling(signal => api.getAutoWatchlist(signal), { intervalMs: 60000, enabled: active && showWatch });

  if (loading) return <div className="p-3"><SkeletonRows rows={8} /></div>;
  if (!data) {
    return (
      <div className="p-3">
        <ErrorBox message={error?.message ?? 'Could not load the auto trader.'} onRetry={refresh} />
      </div>
    );
  }

  const s: AutoTraderState = data;
  const cfg = s.config;
  const value = (k: NumKey | 'trade_mode' | 'stop_loss_action') => draft?.[k] ?? String(cfg[k]);
  const edit = (k: NumKey | 'trade_mode' | 'stop_loss_action', v: string) => {
    setFormError(null);
    setDraft(prev => ({ ...(prev ?? {}), [k]: v }));
  };

  const act = async (id: string, fn: () => Promise<unknown>, ok: string) => {
    setBusyId(id);
    try {
      await fn();
      toast.success(ok);
    } catch (e) {
      toast.error(errorMessage(e));
    } finally {
      setBusyId(null);
      void refresh();
    }
  };

  const save = async () => {
    if (!draft) return;
    const { changes, problem } = buildChanges(cfg, draft);
    if (problem) { setFormError(problem); return; }
    if (Object.keys(changes).length === 0) { setDraft(null); return; }
    setSaving(true);
    setFormError(null);
    try {
      await api.saveAutoConfig(changes);
      toast.success('Configuration saved');
      setDraft(null);
      void refresh();
    } catch (e) {
      setFormError(errorMessage(e));
    } finally {
      setSaving(false);
    }
  };

  const togglePause = () => act('pause', () => api.setAutoPaused(!cfg.trade_paused), cfg.trade_paused ? 'Trading resumed' : 'Trading paused');
  const sum = s.summary;

  return (
    <div className="space-y-3 p-3">
      {error && <ErrorBox message={error.message} onRetry={refresh} stale />}

      {s.warnings.map(w => (
        <div key={w} role="status" className="rounded-md border border-[#4d3d1e] bg-[#1f1a0a] px-3 py-2 text-xs text-warn">⚠ {w}</div>
      ))}

      {/* Status row */}
      <div className="flex flex-wrap items-center gap-2">
        <StatusPill ok={s.worker.alive} text={s.worker.alive ? `Worker running · ${ago(s.worker.age_seconds)}` : `Worker stopped · last seen ${ago(s.worker.age_seconds)}`} />
        <StatusPill ok={s.kite_connected} text={s.kite_connected ? 'Zerodha connected' : 'Zerodha logged out'} />
        <StatusPill ok={s.market_open} text={s.market_open ? 'Market open' : 'Market closed'} />
        <span className="text-[11px] text-muted">
          Intraday only (MIS) · no new entries after {s.rules.entry_cutoff} · everything sold at {s.rules.square_off} IST
        </span>
        <div className="ml-auto flex items-center gap-2">
          <Updated at={updatedAt} refreshing={refreshing} />
          <Btn tone={cfg.trade_paused ? 'primary' : 'warn'} disabled={busyId === 'pause'} onClick={togglePause}>
            {cfg.trade_paused ? '▶ Resume trading' : '⏸ Pause trading'}
          </Btn>
        </div>
      </div>

      {/* Numbers */}
      <div className="grid grid-cols-2 gap-2 md:grid-cols-3 xl:grid-cols-6">
        <Stat label="Total capital" value={`₹${fmtInt(sum.total_capital)}`} />
        <Stat label="Deployed" value={`₹${fmtInt(sum.deployed)}`} />
        <Stat label={sum.available_is_live ? 'Available (live)' : 'Available (est.)'} value={`₹${fmtInt(sum.available)}`} />
        <Stat label="P&L today" value={fmtSigned(sum.pnl_today)} tone={pnlClass(sum.pnl_today)} />
        <Stat label="Active trades" value={`${sum.open_count} / ${sum.max_active_trades}`} />
        <Stat label="Trades today" value={cfg.max_trades_per_day > 0 ? `${s.trades_today} / ${cfg.max_trades_per_day}` : `${s.trades_today} / ∞`} />
      </div>

      {/* Open positions */}
      <Card title={`Open positions (${s.positions.length})`}>
        {s.positions.length === 0 ? (
          <Empty>No open positions.</Empty>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-xs">
              <thead>
                <tr className="border-b border-line text-muted">
                  <th className="px-2 py-1.5 text-left">Contract</th>
                  <th className="px-2 py-1.5 text-right">Qty</th>
                  <th className="px-2 py-1.5 text-right">Avg</th>
                  <th className="px-2 py-1.5 text-right">LTP</th>
                  <th className="px-2 py-1.5 text-right">P&amp;L</th>
                  <th className="px-2 py-1.5 text-right">P&amp;L %</th>
                  <th className="px-2 py-1.5 text-center">Rounds</th>
                  <th className="px-2 py-1.5 text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {s.positions.map((p: AutoPosition) => (
                  <tr key={p.id} className="border-b border-line/30">
                    <td className="px-2 py-1.5">
                      <div className="font-semibold">{p.tradingsymbol}</div>
                      <div className="text-[10px] text-muted">{p.symbol}{p.option_type ? ` · ${p.option_type}` : ''}</div>
                    </td>
                    <td className="px-2 py-1.5 text-right">{fmtInt(p.total_qty)}</td>
                    <td className="px-2 py-1.5 text-right">{fmtPrice(p.avg_price)}</td>
                    <td className="px-2 py-1.5 text-right">{fmtPrice(p.current_price)}</td>
                    <td className={`px-2 py-1.5 text-right font-bold ${pnlClass(p.pnl)}`}>{fmtSigned(p.pnl)}</td>
                    <td className={`px-2 py-1.5 text-right ${pnlClass(p.pnl_pct)}`}>{fmtPct(p.pnl_pct)}</td>
                    <td className="px-2 py-1.5 text-center">{p.rounds}</td>
                    <td className="px-2 py-1.5">
                      <div className="flex justify-end gap-1.5">
                        <Btn small disabled={busyId === p.id}
                          onClick={() => act(p.id, () => api.setAveragingPaused(p.id, !p.paused_averaging),
                            p.paused_averaging ? 'Averaging resumed' : 'Averaging paused')}>
                          {p.paused_averaging ? 'Resume avg' : 'Pause avg'}
                        </Btn>
                        <ConfirmBtn label="Exit now" confirmLabel="Confirm exit" busy={busyId === p.id}
                          onConfirm={() => act(p.id, () => api.exitPosition(p.id), `Exit order filled for ${p.tradingsymbol}`)} />
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {/* Configuration */}
      <Card
        title="Configuration"
        right={draft && <span className="text-[10px] text-warn">Unsaved changes</span>}
      >
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {NUM_FIELDS.map(f => (
            <label key={f.key} className="block text-[11px] text-dim">
              {f.label}
              <input
                type="number"
                inputMode="decimal"
                min={f.min}
                max={f.max}
                step={f.step}
                value={value(f.key)}
                onChange={e => edit(f.key, e.target.value)}
                className="mt-1 w-full rounded-md border border-line bg-panel px-2.5 py-1.5 text-sm text-foreground outline-none focus:border-accent"
              />
              {f.hint && <span className="text-[10px] text-muted">{f.hint}</span>}
            </label>
          ))}
          <label className="block text-[11px] text-dim">
            Trade mode
            <select value={value('trade_mode')} onChange={e => edit('trade_mode', e.target.value)}
              className="mt-1 w-full rounded-md border border-line bg-panel px-2.5 py-1.5 text-sm text-foreground outline-none">
              <option value="OPTIONS">Options (buy CE / PE)</option>
              <option value="EQUITY">Equity</option>
            </select>
          </label>
          <label className="block text-[11px] text-dim">
            At stop-loss
            <select value={value('stop_loss_action')} onChange={e => edit('stop_loss_action', e.target.value)}
              className="mt-1 w-full rounded-md border border-line bg-panel px-2.5 py-1.5 text-sm text-foreground outline-none">
              <option value="EXIT">Exit position</option>
              <option value="AVERAGE">Add one more lot (average)</option>
            </select>
          </label>
        </div>
        {formError && <div className="mt-3"><ErrorBox message={formError} /></div>}
        <div className="mt-3 flex gap-2">
          <Btn tone="primary" disabled={!draft || saving} onClick={save}>{saving ? 'Saving…' : '💾 Save configuration'}</Btn>
          <Btn disabled={!draft || saving} onClick={() => { setDraft(null); setFormError(null); }}>Discard</Btn>
        </div>
      </Card>

      {/* Closed trades */}
      <Card title={`Recent closed trades (${s.closed.length})`}>
        {s.closed.length === 0 ? (
          <Empty>No closed trades yet.</Empty>
        ) : (
          <div className="max-h-80 overflow-auto">
            <table className="w-full border-collapse text-xs">
              <thead className="sticky top-0 bg-card">
                <tr className="border-b border-line text-muted">
                  <th className="px-2 py-1.5 text-left">Contract</th>
                  <th className="px-2 py-1.5 text-right">Qty</th>
                  <th className="px-2 py-1.5 text-right">Avg</th>
                  <th className="px-2 py-1.5 text-right">P&amp;L</th>
                  <th className="px-2 py-1.5 text-center">Reason</th>
                  <th className="px-2 py-1.5 text-right">Closed</th>
                </tr>
              </thead>
              <tbody>
                {s.closed.map(p => (
                  <tr key={p.id} className="border-b border-line/30">
                    <td className="px-2 py-1.5 font-semibold">{p.tradingsymbol}</td>
                    <td className="px-2 py-1.5 text-right">{fmtInt(p.total_qty)}</td>
                    <td className="px-2 py-1.5 text-right">{fmtPrice(p.avg_price)}</td>
                    <td className={`px-2 py-1.5 text-right font-bold ${pnlClass(p.pnl)}`}>{fmtSigned(p.pnl)}</td>
                    <td className="px-2 py-1.5 text-center text-dim">{p.exit_reason ?? '—'}</td>
                    <td className="px-2 py-1.5 text-right text-muted">{fmtTime(p.closed_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {/* Auto-trade watchlist */}
      <Card
        title="Auto-trade watchlist"
        right={<Btn small onClick={() => setShowWatch(v => !v)}>{showWatch ? 'Hide' : 'Show'}</Btn>}
      >
        {!showWatch ? (
          <p className="text-xs text-muted">
            Top 4 stocks per sector with a clear bullish/bearish signal (15m). Bullish → buys the ATM CE, bearish → the ATM PE.
            Only stocks scoring ≥ {cfg.min_entry_score}/5 are traded. Click Show to load.
          </p>
        ) : watch.loading ? (
          <SkeletonRows rows={6} />
        ) : watch.error && !watch.data ? (
          <ErrorBox message={watch.error.message} onRetry={watch.refresh} />
        ) : (
          <div className="max-h-96 overflow-auto">
            <table className="w-full border-collapse text-xs">
              <thead className="sticky top-0 bg-card">
                <tr className="border-b border-line text-muted">
                  {['Stock', 'Sector', 'Price', 'Day %', 'Score', 'Bias', 'Trade'].map(h => <th key={h} className="px-2 py-1.5 text-left">{h}</th>)}
                </tr>
              </thead>
              <tbody>
                {(watch.data ?? []).map(w => (
                  <tr key={w.symbol} className={`border-b border-line/30 ${w.eligible ? '' : 'opacity-45'}`}>
                    <td className="px-2 py-1.5 font-semibold">{w.symbol}</td>
                    <td className="px-2 py-1.5 text-dim">{w.sector}</td>
                    <td className="px-2 py-1.5">₹{fmtPrice(w.spot)}</td>
                    <td className={`px-2 py-1.5 ${pnlClass(w.day_pct)}`}>{fmtPct(w.day_pct)}</td>
                    <td className="px-2 py-1.5 text-warn">{w.score}/5</td>
                    <td className="px-2 py-1.5"><DirBadge dir={w.signal} /></td>
                    <td className="px-2 py-1.5 text-dim">{w.eligible ? `Buy ${w.side}` : `Below min score`}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {(watch.data ?? []).length === 0 && <Empty>No bullish or bearish picks right now.</Empty>}
          </div>
        )}
      </Card>

      {/* Currency helper text kept short: amounts are shown in INR */}
      <p className="pb-2 text-[10px] text-muted">Total capital {fmtRupee(cfg.total_capital)} · per-trade cap {fmtRupee(cfg.total_capital * cfg.max_margin_pct / 100)}</p>
    </div>
  );
}
