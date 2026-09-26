'use client';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { api, errorMessage } from '../lib/api';
import { DEFAULT_WATCHLIST, SECTORS, TABS, isTabKey, type TabKey } from '../lib/constants';
import { useTicker } from '../hooks/useTicker';
import { usePolling } from '../hooks/usePolling';
import { usePersistentState } from '../hooks/usePersistentState';
import { ErrorBoundary } from './ErrorBoundary';
import { NewsTicker } from './NewsTicker';
import { Sidebar } from './Sidebar';
import { StatusBanner } from './StatusBanner';
import { ToastProvider, useToast } from './Toast';
import { AutoTradeLogTab } from './tabs/AutoTradeLogTab';
import { AutoTraderTab } from './tabs/AutoTraderTab';
import { ChartTab } from './tabs/ChartTab';
import { OptionChainTab } from './tabs/OptionChainTab';
import { ScannerTab } from './tabs/ScannerTab';
import { SectorPicksTab } from './tabs/SectorPicksTab';

const isString = (v: unknown): v is string => typeof v === 'string' && v.length > 0;

function initialTab(): TabKey {
  try {
    const fromUrl = new URLSearchParams(window.location.search).get('tab');
    if (isTabKey(fromUrl)) return fromUrl;
    const stored = window.localStorage.getItem('nse.tab');
    if (stored) {
      const parsed: unknown = JSON.parse(stored);
      if (isTabKey(parsed)) return parsed;
    }
  } catch { /* fall through */ }
  return 'chart';
}

function Terminal() {
  const toast = useToast();

  // ── Remembered across reloads ─────────────────────────────────────────────
  const [tab, setTabState] = useState<TabKey>(initialTab);
  const [visited, setVisited] = useState<Set<TabKey>>(() => new Set([tab]));
  const [activeSymbol, setActiveSymbol] = usePersistentState('nse.symbol', 'NIFTY 50', isString);
  const [chartTf, setChartTf] = usePersistentState('nse.chartTf', '5m', isString);
  const [scannerTf, setScannerTf] = usePersistentState('nse.scannerTf', '15m', isString);
  const [sector, setSector] = usePersistentState<string>('nse.sector', SECTORS[0], isString);
  const [sectorTf, setSectorTf] = usePersistentState('nse.sectorTf', '15m', isString);
  const [ocSymbol, setOcSymbol] = usePersistentState('nse.ocSymbol', 'NIFTY', isString);

  const setTab = useCallback((t: TabKey) => {
    setTabState(t);
    setVisited(prev => (prev.has(t) ? prev : new Set(prev).add(t)));
    try {
      window.localStorage.setItem('nse.tab', JSON.stringify(t));
      const url = new URL(window.location.href);
      url.searchParams.set('tab', t);
      window.history.replaceState(null, '', url);
    } catch { /* storage / history unavailable */ }
  }, []);

  // ── Health, indices ───────────────────────────────────────────────────────
  const health = usePolling(signal => api.getHealth(signal), { intervalMs: 15000 });
  const marketOpen = health.data?.market_open ?? false;
  const kiteConnected = health.data?.kite_connected ?? false;
  const indices = usePolling(signal => api.getIndices(signal), { intervalMs: marketOpen ? 15000 : 60000 });

  // ── Zerodha login redirect (?action=login&request_token=…) ────────────────
  const refreshHealth = health.refresh;
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const token = params.get('request_token');
    if (params.get('action') !== 'login' || !token) return;

    // A request_token works exactly once. React StrictMode runs effects twice in dev, and a
    // reload would replay it — remember which tokens were already used.
    const usedKey = `kite.cb.${token}`;
    const cleanUrl = () => {
      const url = new URL(window.location.href);
      ['action', 'request_token', 'status', 'type'].forEach(k => url.searchParams.delete(k));
      window.history.replaceState(null, '', url);
    };
    try {
      if (window.sessionStorage.getItem(usedKey)) { cleanUrl(); return; }
      window.sessionStorage.setItem(usedKey, '1');
    } catch { /* private mode: proceed anyway */ }

    api.kiteCallback(token)
      .then(() => { toast.success('Zerodha connected'); void refreshHealth(); })
      .catch(e => toast.error(`Zerodha login failed: ${errorMessage(e)}`))
      .finally(cleanUrl);
  }, [toast, refreshHealth]);

  // ── Watchlist (server is the source of truth; edits are optimistic with rollback) ──
  const serverWl = usePolling(signal => api.getWatchlist(signal), { intervalMs: null });
  const [localWl, setLocalWl] = useState<string[] | null>(null);
  const watchlist = useMemo(() => {
    const list = localWl ?? serverWl.data;
    return Array.isArray(list) && list.length > 0 ? list : DEFAULT_WATCHLIST;
  }, [localWl, serverWl.data]);

  const addSymbol = useCallback(async (sym: string) => {
    if (watchlist.includes(sym)) { setActiveSymbol(sym); return; }
    const before = watchlist;
    setLocalWl([...before, sym]);
    try {
      await api.addToWatchlist(sym);
    } catch (e) {
      setLocalWl(before);
      toast.error(`Could not add ${sym}: ${errorMessage(e)}`);
    }
  }, [watchlist, setActiveSymbol, toast]);

  const removeSymbol = useCallback(async (sym: string) => {
    const before = watchlist;
    setLocalWl(before.filter(s => s !== sym));
    try {
      await api.removeFromWatchlist(sym);
    } catch (e) {
      setLocalWl(before);
      toast.error(`Could not remove ${sym}: ${errorMessage(e)}`);
    }
  }, [watchlist, toast]);

  // ── Live prices ───────────────────────────────────────────────────────────
  const tickerSymbols = useMemo(() => [...new Set([...watchlist, activeSymbol, 'NIFTY 50', 'BANK NIFTY'])], [watchlist, activeSymbol]);
  const { quotes, status: tickerStatus } = useTicker(tickerSymbols);

  const connectKite = useCallback(async () => {
    try {
      const { url } = await api.getKiteLoginUrl();
      window.location.assign(url);
    } catch (e) {
      toast.error(errorMessage(e));
    }
  }, [toast]);

  const openChart = useCallback((sym: string) => { setActiveSymbol(sym); setTab('chart'); }, [setActiveSymbol, setTab]);

  const apiDown = !!health.error;

  return (
    <div className="flex h-screen overflow-hidden bg-background text-foreground">
      <Sidebar
        watchlist={watchlist}
        active={activeSymbol}
        quotes={quotes}
        indices={indices.data ?? {}}
        kiteConnected={kiteConnected}
        apiDown={apiDown}
        tickerStatus={tickerStatus}
        onSelect={setActiveSymbol}
        onAdd={addSymbol}
        onRemove={removeSymbol}
        onConnectKite={connectKite}
      />

      <main className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <StatusBanner
          apiDown={apiDown}
          apiError={health.error?.message}
          kiteConnected={kiteConnected}
          kiteConfigured={health.data?.kite_configured ?? true}
          onRetry={health.refresh}
        />

        <div role="tablist" aria-label="Sections" className="flex overflow-x-auto border-b border-line bg-panel">
          {TABS.map(t => (
            <button
              key={t.key}
              role="tab"
              type="button"
              aria-selected={tab === t.key}
              onClick={() => setTab(t.key)}
              className={`whitespace-nowrap border-b-2 px-[18px] py-2.5 text-[13px] ${
                tab === t.key ? 'border-accent font-semibold text-foreground' : 'border-transparent text-muted hover:text-dim'
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>

        {/* Tabs mount on first visit and then stay mounted (hidden) so switching is instant and
            keeps their state; only the visible tab polls. */}
        <div className="min-h-0 flex-1 overflow-auto">
          {TABS.filter(t => visited.has(t.key)).map(t => {
            const active = tab === t.key;
            return (
              <div key={t.key} role="tabpanel" hidden={!active} className={active ? 'h-full' : 'hidden'}>
                <ErrorBoundary label={t.label.replace(/^\S+\s/, '')}>
                  {t.key === 'chart' && <ChartTab symbol={activeSymbol} quote={quotes[activeSymbol]} tf={chartTf} onTf={setChartTf} />}
                  {t.key === 'optionchain' && <OptionChainTab symbol={ocSymbol} onSymbol={setOcSymbol} marketOpen={marketOpen} active={active} />}
                  {t.key === 'scanner' && <ScannerTab tf={scannerTf} onTf={setScannerTf} onPick={openChart} active={active} />}
                  {t.key === 'sectorpicks' && <SectorPicksTab sector={sector} onSector={setSector} tf={sectorTf} onTf={setSectorTf} onPick={openChart} active={active} />}
                  {t.key === 'autotrader' && <AutoTraderTab active={active} marketOpen={marketOpen} />}
                  {t.key === 'autolog' && <AutoTradeLogTab active={active} marketOpen={marketOpen} />}
                </ErrorBoundary>
              </div>
            );
          })}
        </div>

        <NewsTicker />
      </main>
    </div>
  );
}

export default function Dashboard() {
  return (
    <ToastProvider>
      <Terminal />
    </ToastProvider>
  );
}
