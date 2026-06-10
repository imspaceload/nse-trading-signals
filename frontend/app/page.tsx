'use client';
import { useEffect, useState, useCallback, useRef } from 'react';
import { api } from '../lib/api';
import { useTicker } from '../hooks/useTicker';

// ── Types ─────────────────────────────────────────────────────────────────

interface ScannerRow {
  symbol: string;
  spot: number;
  score: number;
  direction: 'BUY' | 'SELL' | 'NEUTRAL';
  rsi: number;
  macd: string;
  supertrend: 'BULL' | 'BEAR';
  vwap: string;
  vol_spike: boolean;
  day_pct: number;
}

interface OptionRow {
  strikePrice: number;
  CE?: { lastPrice: number; openInterest: number; impliedVolatility: number; totalTradedVolume: number };
  PE?: { lastPrice: number; openInterest: number; impliedVolatility: number; totalTradedVolume: number };
}

interface NewsItem {
  title: string;
  url?: string;
  sentiment?: string;
}

const SECTORS = [
  'Banking 🏦',
  'IT / Tech 💻',
  'Auto 🚗',
  'Pharma 💊',
  'FMCG 🛒',
  'Metal & Mining ⛏',
  'Energy & Oil ⚡',
  'Infrastructure 🏗',
  'Telecom 📡',
  'Consumer & Retail 🛍',
  'Financial Services 📈',
];

const TV_SYMBOL: Record<string, string> = {
  'NIFTY 50':    'NSE:NIFTY',
  'BANK NIFTY':  'NSE:BANKNIFTY',
  'FIN NIFTY':   'NSE:FINNIFTY',
  'SENSEX':      'BSE:SENSEX',
  'INDIA VIX':   'NSE:INDIAVIX',
};
function toTvSymbol(sym: string) {
  return TV_SYMBOL[sym] ?? `NSE:${sym.replace(/[^A-Z0-9&-]/gi, '').toUpperCase()}`;
}

const TIMEFRAMES = ['1m', '3m', '5m', '15m', '1h', '1D'];
const TV_INT: Record<string, string> = { '1m': '1', '3m': '3', '5m': '5', '15m': '15', '1h': '60', '1D': 'D' };

// ── Helpers ───────────────────────────────────────────────────────────────

function pctColor(pct: number) {
  return pct >= 0 ? '#4caf50' : '#ef4444';
}

function dirBadge(dir: string) {
  if (dir === 'BUY') return <span className="px-2 py-0.5 rounded text-xs font-bold bg-green-900/60 text-green-400 border border-green-800">BUY</span>;
  if (dir === 'SELL') return <span className="px-2 py-0.5 rounded text-xs font-bold bg-red-900/60 text-red-400 border border-red-800">SELL</span>;
  return <span className="px-2 py-0.5 rounded text-xs font-bold bg-gray-800 text-gray-400 border border-gray-700">NEUTRAL</span>;
}

function stBadge(st: string) {
  if (st === 'BULL') return <span style={{ color: '#4caf50', fontSize: '0.9em', fontWeight: 600 }}>▲ BULL</span>;
  return <span style={{ color: '#ef4444', fontSize: '0.9em', fontWeight: 600 }}>▼ BEAR</span>;
}

// ── Main Component ────────────────────────────────────────────────────────

export default function TradingTerminal() {
  const [watchlist, setWatchlist] = useState<string[]>([]);
  const [activeSymbol, setActiveSymbol] = useState('NIFTY 50');
  const [activeTab, setActiveTab] = useState<'chart' | 'optionchain' | 'scanner' | 'sectorpicks' | 'smsadmin'>('chart');
  const [chartTf, setChartTf] = useState('5m');
  const [kiteConnected, setKiteConnected] = useState(false);

  // Scanner state
  const [scannerTf, setScannerTf] = useState('15m');
  const [scannerData, setScannerData] = useState<ScannerRow[]>([]);
  const [scannerLoading, setScannerLoading] = useState(false);
  const scannerTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  // Sector picks state
  const [selectedSector, setSelectedSector] = useState(SECTORS[0]);
  const [sectorTf, setSectorTf] = useState('15m');
  const [sectorData, setSectorData] = useState<ScannerRow[]>([]);
  const [sectorLoading, setSectorLoading] = useState(false);

  // Option chain state
  const [ocSymbol, setOcSymbol] = useState('NIFTY');
  const [ocData, setOcData] = useState<OptionRow[]>([]);
  const [ocExpiries, setOcExpiries] = useState<string[]>([]);
  const [ocSpot, setOcSpot] = useState(0);
  const [ocLoading, setOcLoading] = useState(false);

  // News state
  const [newsItems, setNewsItems] = useState<NewsItem[]>([]);

  // Watchlist add input
  const [wlInput, setWlInput] = useState('');

  // Ticker: always subscribe to watchlist + active symbol
  const tickerSymbols = [...new Set([...watchlist, activeSymbol])];
  const quotes = useTicker(tickerSymbols);

  // Indices
  const [indices, setIndices] = useState<Record<string, { price: number; pct: number; change: number }>>({});

  // ── Kite OAuth callback handler ──────────────────────────────────────────
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get('action') === 'login' && params.get('request_token')) {
      api.kiteCallback(params.get('request_token')!)
        .then(() => { setKiteConnected(true); window.history.replaceState({}, '', '/'); })
        .catch(() => {});
    }
  }, []);

  // ── Load initial data ────────────────────────────────────────────────────

  useEffect(() => {
    api.getHealth().then(h => setKiteConnected(h?.kite_connected ?? false)).catch(() => {});
    // Poll health every 30s to detect Kite reconnection
    const t = setInterval(() => api.getHealth().then(h => setKiteConnected(h?.kite_connected ?? false)).catch(() => {}), 30000);
    api.getWatchlist()
      .then((wl: string[]) => {
        if (Array.isArray(wl) && wl.length > 0) {
          setWatchlist(wl);
        } else {
          const defaults = ['NIFTY 50', 'BANK NIFTY', 'RELIANCE', 'HDFCBANK', 'TCS', 'INFY'];
          setWatchlist(defaults);
        }
      })
      .catch(() => setWatchlist(['NIFTY 50', 'BANK NIFTY', 'RELIANCE', 'HDFCBANK', 'TCS', 'INFY']));

    api.getIndices()
      .then(data => { if (data && typeof data === 'object') setIndices(data); })
      .catch(() => {});
    return () => clearInterval(t);
  }, []);

  // Auto-refresh indices every 15s
  useEffect(() => {
    const t = setInterval(() => {
      api.getIndices()
        .then(data => { if (data && typeof data === 'object') setIndices(data); })
        .catch(() => {});
    }, 15000);
    return () => clearInterval(t);
  }, []);

  // ── Scanner ──────────────────────────────────────────────────────────────

  const loadScanner = useCallback(() => {
    setScannerLoading(true);
    api.getScanner(scannerTf)
      .then((data: ScannerRow[]) => {
        if (Array.isArray(data)) setScannerData(data);
      })
      .catch(() => {})
      .finally(() => setScannerLoading(false));
  }, [scannerTf]);

  useEffect(() => {
    if (activeTab === 'scanner') {
      loadScanner();
      const t = setInterval(loadScanner, 30000);
      scannerTimer.current = t;
    }
    return () => clearInterval(scannerTimer.current);
  }, [activeTab, loadScanner]);

  // ── Sector Picks ─────────────────────────────────────────────────────────

  const loadSectorPicks = useCallback(() => {
    setSectorLoading(true);
    api.getSectorPicks(selectedSector, sectorTf)
      .then((data: ScannerRow[]) => {
        if (Array.isArray(data)) setSectorData(data);
      })
      .catch(() => {})
      .finally(() => setSectorLoading(false));
  }, [selectedSector, sectorTf]);

  useEffect(() => {
    if (activeTab === 'sectorpicks') loadSectorPicks();
  }, [activeTab, loadSectorPicks]);

  // ── Option Chain ─────────────────────────────────────────────────────────

  const loadOptionChain = useCallback(() => {
    setOcLoading(true);
    api.getOptionChain(ocSymbol)
      .then((data) => {
        const records = data?.records;
        if (records) {
          setOcData(records.data || []);
          setOcExpiries(records.expiryDates || []);
          setOcSpot(records.underlyingValue || 0);
        }
      })
      .catch(() => {})
      .finally(() => setOcLoading(false));
  }, [ocSymbol]);

  useEffect(() => {
    if (activeTab === 'optionchain') loadOptionChain();
  }, [activeTab, loadOptionChain]);

  // ── News (load once) ─────────────────────────────────────────────────────

  useEffect(() => {
    api.getNews()
      .then((data: NewsItem[]) => { if (Array.isArray(data)) setNewsItems(data); })
      .catch(() => {});
  }, []);

  // ── Watchlist management ─────────────────────────────────────────────────

  const handleAddWatchlist = () => {
    const sym = wlInput.trim().toUpperCase();
    if (!sym) return;
    api.addToWatchlist(sym)
      .then(() => {
        setWatchlist(prev => prev.includes(sym) ? prev : [...prev, sym]);
        setWlInput('');
      })
      .catch(() => {});
  };

  const handleRemoveWatchlist = (sym: string) => {
    api.removeFromWatchlist(sym)
      .then(() => setWatchlist(prev => prev.filter(s => s !== sym)))
      .catch(() => {});
  };

  // ── ATM strike helper ────────────────────────────────────────────────────

  const atm = ocSpot > 0
    ? (ocSpot < 5000 ? Math.round(ocSpot / 50) * 50 : Math.round(ocSpot / 100) * 100)
    : 0;

  // ─────────────────────────────────────────────────────────────────────────
  //  RENDER
  // ─────────────────────────────────────────────────────────────────────────

  return (
    <div className="flex h-screen overflow-hidden" style={{ background: '#0a0a14', color: '#e8e8e8', fontFamily: 'Inter, sans-serif' }}>

      {/* ── LEFT SIDEBAR: Watchlist ─────────────────────────────────────── */}
      <aside
        style={{
          width: '220px', minWidth: '220px', borderRight: '1px solid #2a2a4a',
          background: '#0d0d1a', display: 'flex', flexDirection: 'column', overflow: 'hidden',
        }}
      >
        {/* Header */}
        <div style={{ padding: '10px 12px 8px', borderBottom: '1px solid #2a2a4a', background: '#141428' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <span style={{ fontSize: '0.88em', fontWeight: 700 }}>Options Terminal</span>
            <span style={{
              background: kiteConnected ? '#4caf5022' : '#ef444422',
              color: kiteConnected ? '#4caf50' : '#ef4444',
              padding: '1px 7px', borderRadius: '10px', fontSize: '0.55em', fontWeight: 700,
            }}>
              {kiteConnected ? '● LIVE' : '● OFFLINE'}
            </span>
          </div>
          {/* Kite connect button — shown when offline */}
          {!kiteConnected && (
            <button
              onClick={() => api.kiteLoginUrl().then((d: {url: string}) => { if (d?.url) window.open(d.url, '_self'); }).catch(() => {})}
              style={{
                marginTop: '6px', width: '100%', background: '#1e3a5f',
                border: '1px solid #2a4a6f', borderRadius: '5px', color: '#60a5fa',
                fontSize: '0.68em', fontWeight: 700, padding: '5px 8px', cursor: 'pointer',
              }}
            >
              🔑 Connect Zerodha Kite
            </button>
          )}
        </div>

        {/* Index strip */}
        <div style={{ padding: '6px 8px', borderBottom: '1px solid #1e1e2e', background: '#0f0f1e' }}>
          {(['NIFTY 50', 'BANK NIFTY'] as const).map(idx => {
            const q = quotes[idx];
            const ltp = q?.ltp ?? (indices[idx]?.price ?? 0);
            const pct = q?.pct ?? (indices[idx]?.pct ?? 0);
            if (!ltp) return null;
            return (
              <div key={idx} style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '2px' }}>
                <span style={{ fontSize: '0.65em', color: '#9ca3af' }}>{idx === 'NIFTY 50' ? 'NIFTY' : 'BANKNIFTY'}</span>
                <span style={{ fontSize: '0.65em', color: pctColor(pct), fontWeight: 600 }}>
                  {ltp.toLocaleString('en-IN', { maximumFractionDigits: 0 })} {pct >= 0 ? '▲' : '▼'}{Math.abs(pct).toFixed(2)}%
                </span>
              </div>
            );
          })}
        </div>

        {/* Add to watchlist */}
        <div style={{ padding: '6px 8px', borderBottom: '1px solid #1e1e2e' }}>
          <div style={{ display: 'flex', gap: '4px' }}>
            <input
              type="text"
              placeholder="+ Add symbol"
              value={wlInput}
              onChange={e => setWlInput(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleAddWatchlist()}
              style={{
                flex: 1, background: '#12121f', border: '1px solid #2a2a4a', borderRadius: '5px',
                color: '#e8e8e8', fontSize: '0.72em', padding: '5px 8px', outline: 'none',
              }}
            />
            <button
              onClick={handleAddWatchlist}
              style={{
                background: '#1e3a5f', border: '1px solid #2a4a6f', borderRadius: '5px',
                color: '#60a5fa', fontSize: '0.8em', padding: '4px 8px', cursor: 'pointer',
              }}
            >+</button>
          </div>
        </div>

        {/* Watchlist items */}
        <div style={{ flex: 1, overflowY: 'auto' }}>
          <div style={{ padding: '4px 8px 2px', color: '#374151', fontSize: '0.5em', textTransform: 'uppercase', letterSpacing: '1px' }}>
            WATCHLIST
          </div>
          {watchlist.map(sym => {
            const q = quotes[sym];
            const ltp = q?.ltp;
            const pct = q?.pct;
            const change = q?.change;
            const isActive = sym === activeSymbol;

            return (
              <div
                key={sym}
                onClick={() => setActiveSymbol(sym)}
                style={{
                  display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                  padding: '8px 10px 8px 12px',
                  borderBottom: '1px solid rgba(42,42,74,0.35)',
                  borderLeft: isActive ? '3px solid #387ed1' : '3px solid transparent',
                  background: isActive ? 'rgba(56,126,209,0.07)' : 'transparent',
                  cursor: 'pointer',
                }}
              >
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{
                    fontSize: '0.78em', fontWeight: 600,
                    color: isActive ? '#60a5fa' : '#e8e8e8',
                    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                  }}>
                    {sym}
                  </div>
                  {ltp !== undefined && (
                    <div style={{ fontSize: '0.6em', color: pctColor(pct ?? 0), marginTop: '1px' }}>
                      {ltp.toLocaleString('en-IN', { maximumFractionDigits: 2 })}
                      {pct !== undefined && (
                        <span style={{ marginLeft: '4px' }}>
                          {pct >= 0 ? '▲' : '▼'}{Math.abs(pct).toFixed(2)}%
                        </span>
                      )}
                    </div>
                  )}
                  {change !== undefined && change !== 0 && (
                    <div style={{ fontSize: '0.55em', color: pctColor(change) }}>
                      {change >= 0 ? '+' : ''}{change.toFixed(2)}
                    </div>
                  )}
                </div>
                <button
                  onClick={e => { e.stopPropagation(); handleRemoveWatchlist(sym); }}
                  style={{
                    background: 'transparent', border: 'none', color: '#4b5563',
                    fontSize: '0.7em', cursor: 'pointer', padding: '0 2px', marginLeft: '4px',
                  }}
                >✕</button>
              </div>
            );
          })}
        </div>
      </aside>

      {/* ── MAIN AREA ────────────────────────────────────────────────────── */}
      <main style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>

        {/* Tab bar */}
        <div style={{ display: 'flex', borderBottom: '1px solid #2a2a4a', background: '#0d0d1a' }}>
          {([
            { key: 'chart', label: '📈 Chart' },
            { key: 'optionchain', label: '⛓ Option Chain' },
            { key: 'scanner', label: '📊 Scanner' },
            { key: 'sectorpicks', label: '🎯 Sector Picks' },
            { key: 'smsadmin', label: '📱 SMS Admin' },
          ] as const).map(t => (
            <button
              key={t.key}
              onClick={() => setActiveTab(t.key)}
              style={{
                padding: '10px 18px', background: 'transparent', border: 'none',
                borderBottom: activeTab === t.key ? '2px solid #387ed1' : '2px solid transparent',
                color: activeTab === t.key ? '#e8e8e8' : '#6b7280',
                fontSize: '0.82em', fontWeight: activeTab === t.key ? 600 : 400,
                cursor: 'pointer',
              }}
            >
              {t.label}
            </button>
          ))}
        </div>

        {/* Tab content */}
        <div style={{ flex: 1, overflow: 'auto' }}>

          {/* ── CHART TAB ────────────────────────────────────────────────── */}
          {activeTab === 'chart' && (
            <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
              {/* Symbol header */}
              <div style={{
                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                padding: '8px 12px', borderBottom: '1px solid #2a2a4a', flexShrink: 0,
              }}>
                <div style={{ display: 'flex', alignItems: 'baseline', gap: '10px' }}>
                  <span style={{ fontSize: '1.15em', fontWeight: 700 }}>{activeSymbol}</span>
                  <span style={{ color: '#4b5563', fontSize: '0.65em' }}>NSE</span>
                  {quotes[activeSymbol] && (
                    <>
                      <span style={{ fontSize: '1.1em', fontWeight: 700 }}>
                        ₹{(quotes[activeSymbol].ltp || 0).toLocaleString('en-IN', { maximumFractionDigits: 2 })}
                      </span>
                      <span style={{ color: pctColor(quotes[activeSymbol].pct), fontSize: '0.82em', fontWeight: 600 }}>
                        {quotes[activeSymbol].pct >= 0 ? '▲' : '▼'} {Math.abs(quotes[activeSymbol].pct).toFixed(2)}%
                      </span>
                    </>
                  )}
                </div>
                {/* Timeframe selector */}
                <div style={{ display: 'flex', gap: '3px', background: '#12121f', border: '1px solid #2a2a4a', borderRadius: '6px', padding: '3px' }}>
                  {TIMEFRAMES.map(tf => (
                    <button
                      key={tf}
                      onClick={() => setChartTf(tf)}
                      style={{
                        padding: '3px 9px', borderRadius: '4px', border: 'none',
                        background: chartTf === tf ? '#1e293b' : 'transparent',
                        color: chartTf === tf ? '#e8e8e8' : '#6b7280',
                        fontSize: '0.72em', fontWeight: chartTf === tf ? 600 : 400, cursor: 'pointer',
                      }}
                    >
                      {tf}
                    </button>
                  ))}
                </div>
              </div>

              {/* TradingView iframe */}
              <div style={{ flex: 1 }}>
                <iframe
                  key={`${activeSymbol}-${chartTf}`}
                  src={`https://s.tradingview.com/widgetembed/?symbol=${toTvSymbol(activeSymbol)}&interval=${TV_INT[chartTf] || '5'}&theme=dark&style=1&locale=en&toolbar_bg=%230a0a14&enable_publishing=0&hide_top_toolbar=0&hide_legend=0&save_image=0&hide_side_toolbar=0`}
                  style={{ width: '100%', height: '100%', border: 'none', minHeight: '500px' }}
                  allowFullScreen
                />
              </div>
            </div>
          )}

          {/* ── OPTION CHAIN TAB ─────────────────────────────────────────── */}
          {activeTab === 'optionchain' && (
            <div style={{ padding: '12px' }}>
              {/* Controls */}
              <div style={{ display: 'flex', gap: '10px', alignItems: 'center', marginBottom: '12px', flexWrap: 'wrap' }}>
                <input
                  type="text"
                  value={ocSymbol}
                  onChange={e => setOcSymbol(e.target.value.toUpperCase())}
                  placeholder="Symbol (NIFTY, BANKNIFTY...)"
                  style={{
                    background: '#12121f', border: '1px solid #2a2a4a', borderRadius: '6px',
                    color: '#e8e8e8', fontSize: '0.82em', padding: '6px 10px', width: '200px', outline: 'none',
                  }}
                />
                <button
                  onClick={loadOptionChain}
                  disabled={ocLoading}
                  style={{
                    background: '#1e3a5f', border: '1px solid #2a4a6f', borderRadius: '6px',
                    color: '#60a5fa', fontSize: '0.82em', padding: '6px 14px', cursor: 'pointer',
                  }}
                >
                  {ocLoading ? 'Loading...' : 'Load Chain'}
                </button>
                {ocSpot > 0 && (
                  <span style={{ color: '#9ca3af', fontSize: '0.78em' }}>
                    Spot: <strong style={{ color: '#e8e8e8' }}>₹{ocSpot.toLocaleString('en-IN', { maximumFractionDigits: 0 })}</strong>
                    &nbsp;&nbsp; ATM: <strong style={{ color: '#fbbf24' }}>{atm}</strong>
                  </span>
                )}
                {ocExpiries.length > 0 && (
                  <span style={{ color: '#6b7280', fontSize: '0.72em' }}>Expiry: {ocExpiries[0]}</span>
                )}
              </div>

              {/* Table */}
              {ocData.length > 0 && (
                <div style={{ overflowX: 'auto' }}>
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.78em' }}>
                    <thead>
                      <tr style={{ borderBottom: '1px solid #2a2a4a', color: '#6b7280' }}>
                        <th style={{ textAlign: 'right', padding: '6px 8px' }}>CE OI</th>
                        <th style={{ textAlign: 'right', padding: '6px 8px' }}>CE IV</th>
                        <th style={{ textAlign: 'right', padding: '6px 8px' }}>CE LTP</th>
                        <th style={{ textAlign: 'center', padding: '6px 8px', color: '#fbbf24', fontWeight: 700 }}>STRIKE</th>
                        <th style={{ textAlign: 'left', padding: '6px 8px' }}>PE LTP</th>
                        <th style={{ textAlign: 'left', padding: '6px 8px' }}>PE IV</th>
                        <th style={{ textAlign: 'left', padding: '6px 8px' }}>PE OI</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(() => {
                        const atmIdx = ocData.findIndex(r => r.strikePrice >= atm);
                        const start = Math.max(0, atmIdx - 8);
                        const end = Math.min(ocData.length, atmIdx + 9);
                        return ocData.slice(start, end).filter(row => row.CE || row.PE).map(row => {
                          const isAtm = atm > 0 && Math.abs(row.strikePrice - atm) < 1;
                          return (
                            <tr
                              key={row.strikePrice}
                              style={{
                                borderBottom: '1px solid rgba(42,42,74,0.4)',
                                background: isAtm ? 'rgba(251,191,36,0.06)' : 'transparent',
                              }}
                            >
                              <td style={{ textAlign: 'right', padding: '5px 8px', color: '#4caf50' }}>
                                {row.CE?.openInterest ? (row.CE.openInterest / 1000).toFixed(0) + 'K' : '--'}
                              </td>
                              <td style={{ textAlign: 'right', padding: '5px 8px', color: '#9ca3af' }}>
                                {row.CE?.impliedVolatility ? row.CE.impliedVolatility.toFixed(1) + '%' : '--'}
                              </td>
                              <td style={{ textAlign: 'right', padding: '5px 8px', color: '#4caf50', fontWeight: 600 }}>
                                {row.CE?.lastPrice ? row.CE.lastPrice.toFixed(2) : '--'}
                              </td>
                              <td style={{
                                textAlign: 'center', padding: '5px 10px',
                                fontWeight: 700, fontSize: '0.9em',
                                color: isAtm ? '#fbbf24' : '#e8e8e8',
                              }}>
                                {row.strikePrice.toLocaleString('en-IN')}
                                {isAtm && <span style={{ color: '#fbbf24', fontSize: '0.65em', marginLeft: '4px' }}>ATM</span>}
                              </td>
                              <td style={{ textAlign: 'left', padding: '5px 8px', color: '#ef4444', fontWeight: 600 }}>
                                {row.PE?.lastPrice ? row.PE.lastPrice.toFixed(2) : '--'}
                              </td>
                              <td style={{ textAlign: 'left', padding: '5px 8px', color: '#9ca3af' }}>
                                {row.PE?.impliedVolatility ? row.PE.impliedVolatility.toFixed(1) + '%' : '--'}
                              </td>
                              <td style={{ textAlign: 'left', padding: '5px 8px', color: '#ef4444' }}>
                                {row.PE?.openInterest ? (row.PE.openInterest / 1000).toFixed(0) + 'K' : '--'}
                              </td>
                            </tr>
                          );
                        });
                      })()}
                    </tbody>
                  </table>
                </div>
              )}

              {ocData.length === 0 && !ocLoading && (
                <div style={{ color: '#4b5563', fontSize: '0.82em', marginTop: '20px', textAlign: 'center' }}>
                  Enter a symbol and click &ldquo;Load Chain&rdquo; to view the option chain.
                </div>
              )}
            </div>
          )}

          {/* ── SCANNER TAB ──────────────────────────────────────────────── */}
          {activeTab === 'scanner' && (
            <div style={{ padding: '12px' }}>
              {/* Controls */}
              <div style={{ display: 'flex', gap: '8px', alignItems: 'center', marginBottom: '12px', flexWrap: 'wrap' }}>
                <span style={{ color: '#9ca3af', fontSize: '0.78em' }}>Timeframe:</span>
                <div style={{ display: 'flex', gap: '2px', background: '#12121f', border: '1px solid #2a2a4a', borderRadius: '6px', padding: '2px' }}>
                  {['5m', '15m', '1h', '1D'].map(tf => (
                    <button
                      key={tf}
                      onClick={() => setScannerTf(tf)}
                      style={{
                        padding: '3px 10px', borderRadius: '4px', border: 'none',
                        background: scannerTf === tf ? '#1e293b' : 'transparent',
                        color: scannerTf === tf ? '#e8e8e8' : '#6b7280',
                        fontSize: '0.72em', cursor: 'pointer',
                      }}
                    >{tf}</button>
                  ))}
                </div>
                <button
                  onClick={loadScanner}
                  disabled={scannerLoading}
                  style={{
                    background: '#1e3a5f', border: '1px solid #2a4a6f', borderRadius: '6px',
                    color: '#60a5fa', fontSize: '0.78em', padding: '5px 12px', cursor: 'pointer',
                  }}
                >{scannerLoading ? '⟳ Scanning...' : '⟳ Refresh'}</button>
                <span style={{ color: '#4b5563', fontSize: '0.65em' }}>Auto-refresh every 30s</span>
              </div>

              {/* Table */}
              {scannerData.length > 0 && (
                <div style={{ overflowX: 'auto' }}>
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.78em' }}>
                    <thead>
                      <tr style={{ borderBottom: '1px solid #2a2a4a', color: '#6b7280' }}>
                        <th style={{ textAlign: 'left', padding: '6px 10px' }}>#</th>
                        <th style={{ textAlign: 'left', padding: '6px 10px' }}>Symbol</th>
                        <th style={{ textAlign: 'right', padding: '6px 10px' }}>Price</th>
                        <th style={{ textAlign: 'center', padding: '6px 10px' }}>Signal</th>
                        <th style={{ textAlign: 'center', padding: '6px 10px' }}>Score</th>
                        <th style={{ textAlign: 'right', padding: '6px 10px' }}>RSI</th>
                        <th style={{ textAlign: 'center', padding: '6px 10px' }}>MACD</th>
                        <th style={{ textAlign: 'center', padding: '6px 10px' }}>ST</th>
                        <th style={{ textAlign: 'center', padding: '6px 10px' }}>VWAP</th>
                        <th style={{ textAlign: 'right', padding: '6px 10px' }}>Day%</th>
                        <th style={{ textAlign: 'center', padding: '6px 10px' }}>Vol</th>
                      </tr>
                    </thead>
                    <tbody>
                      {scannerData.map((row, i) => (
                        <tr
                          key={row.symbol}
                          onClick={() => { setActiveSymbol(row.symbol); setActiveTab('chart'); }}
                          style={{
                            borderBottom: '1px solid rgba(42,42,74,0.3)',
                            cursor: 'pointer',
                            background: row.direction === 'BUY' ? 'rgba(76,175,80,0.03)' : row.direction === 'SELL' ? 'rgba(239,68,68,0.03)' : 'transparent',
                          }}
                        >
                          <td style={{ padding: '5px 10px', color: '#4b5563' }}>{i + 1}</td>
                          <td style={{ padding: '5px 10px', color: '#e8e8e8', fontWeight: 600 }}>{row.symbol}</td>
                          <td style={{ padding: '5px 10px', textAlign: 'right', color: '#e8e8e8' }}>
                            ₹{row.spot.toLocaleString('en-IN', { maximumFractionDigits: 2 })}
                          </td>
                          <td style={{ padding: '5px 10px', textAlign: 'center' }}>{dirBadge(row.direction)}</td>
                          <td style={{ padding: '5px 10px', textAlign: 'center' }}>
                            <span style={{ display: 'inline-flex', gap: '2px', alignItems: 'center' }}>
                              {[1, 2, 3, 4, 5].map(n => (
                                <span
                                  key={n}
                                  style={{
                                    width: '7px', height: '7px', borderRadius: '2px',
                                    background: n <= row.score
                                      ? (row.direction === 'BUY' ? '#4caf50' : row.direction === 'SELL' ? '#ef4444' : '#6b7280')
                                      : '#1e1e2e',
                                  }}
                                />
                              ))}
                            </span>
                          </td>
                          <td style={{ padding: '5px 10px', textAlign: 'right', color: row.rsi < 40 ? '#4caf50' : row.rsi > 60 ? '#ef4444' : '#9ca3af' }}>
                            {row.rsi.toFixed(1)}
                          </td>
                          <td style={{ padding: '5px 10px', textAlign: 'center', color: row.macd === 'BUY' ? '#4caf50' : row.macd === 'SELL' ? '#ef4444' : '#6b7280' }}>
                            {row.macd}
                          </td>
                          <td style={{ padding: '5px 10px', textAlign: 'center' }}>{stBadge(row.supertrend)}</td>
                          <td style={{ padding: '5px 10px', textAlign: 'center', color: row.vwap === 'BUY' ? '#4caf50' : row.vwap === 'SELL' ? '#ef4444' : '#6b7280' }}>
                            {row.vwap}
                          </td>
                          <td style={{ padding: '5px 10px', textAlign: 'right', color: pctColor(row.day_pct) }}>
                            {row.day_pct >= 0 ? '+' : ''}{row.day_pct.toFixed(2)}%
                          </td>
                          <td style={{ padding: '5px 10px', textAlign: 'center', color: row.vol_spike ? '#fbbf24' : '#4b5563' }}>
                            {row.vol_spike ? 'SPIKE' : '--'}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {scannerData.length === 0 && !scannerLoading && (
                <div style={{ color: '#4b5563', fontSize: '0.82em', marginTop: '20px', textAlign: 'center' }}>
                  Scanner runs on tab open. Click Refresh to scan now.
                </div>
              )}
              {scannerLoading && (
                <div style={{ color: '#6b7280', fontSize: '0.82em', marginTop: '20px', textAlign: 'center' }}>
                  Scanning stocks across all sectors...
                </div>
              )}
            </div>
          )}

          {/* ── SECTOR PICKS TAB ─────────────────────────────────────────── */}
          {activeTab === 'sectorpicks' && (
            <div style={{ padding: '12px' }}>
              {/* Controls */}
              <div style={{ display: 'flex', gap: '10px', alignItems: 'center', flexWrap: 'wrap', marginBottom: '16px' }}>
                <select
                  value={selectedSector}
                  onChange={e => setSelectedSector(e.target.value)}
                  style={{
                    background: '#12121f', border: '1px solid #2a2a4a', borderRadius: '6px',
                    color: '#e8e8e8', fontSize: '0.82em', padding: '6px 10px', outline: 'none', cursor: 'pointer',
                  }}
                >
                  {SECTORS.map(s => <option key={s} value={s}>{s}</option>)}
                </select>
                <div style={{ display: 'flex', gap: '2px', background: '#12121f', border: '1px solid #2a2a4a', borderRadius: '6px', padding: '2px' }}>
                  {['5m', '15m', '1h', '1D'].map(tf => (
                    <button
                      key={tf}
                      onClick={() => setSectorTf(tf)}
                      style={{
                        padding: '3px 10px', borderRadius: '4px', border: 'none',
                        background: sectorTf === tf ? '#1e293b' : 'transparent',
                        color: sectorTf === tf ? '#e8e8e8' : '#6b7280',
                        fontSize: '0.72em', cursor: 'pointer',
                      }}
                    >{tf}</button>
                  ))}
                </div>
                <button
                  onClick={loadSectorPicks}
                  disabled={sectorLoading}
                  style={{
                    background: '#1e3a5f', border: '1px solid #2a4a6f', borderRadius: '6px',
                    color: '#60a5fa', fontSize: '0.78em', padding: '5px 12px', cursor: 'pointer',
                  }}
                >{sectorLoading ? 'Loading...' : '⟳ Refresh'}</button>
              </div>

              {/* Cards grid */}
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: '12px' }}>
                {sectorData.slice(0, 4).map(stock => (
                  <div
                    key={stock.symbol}
                    onClick={() => { setActiveSymbol(stock.symbol); setActiveTab('chart'); }}
                    style={{
                      background: '#0f0f1e',
                      border: `1px solid ${stock.direction === 'BUY' ? '#1e4d1e' : stock.direction === 'SELL' ? '#4d1e1e' : '#2a2a4a'}`,
                      borderRadius: '8px', padding: '14px', cursor: 'pointer',
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '10px' }}>
                      <div>
                        <div style={{ fontSize: '1em', fontWeight: 700, color: '#e8e8e8' }}>{stock.symbol}</div>
                        <div style={{ fontSize: '0.75em', color: '#9ca3af', marginTop: '1px' }}>NSE · F&amp;O</div>
                      </div>
                      {dirBadge(stock.direction)}
                    </div>

                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
                      <div>
                        <div style={{ fontSize: '0.6em', color: '#6b7280', textTransform: 'uppercase' }}>Price</div>
                        <div style={{ fontSize: '1em', fontWeight: 700, color: '#e8e8e8' }}>
                          ₹{stock.spot.toLocaleString('en-IN', { maximumFractionDigits: 2 })}
                        </div>
                      </div>
                      <div style={{ textAlign: 'right' }}>
                        <div style={{ fontSize: '0.6em', color: '#6b7280', textTransform: 'uppercase' }}>Day Change</div>
                        <div style={{ fontSize: '1em', fontWeight: 700, color: pctColor(stock.day_pct) }}>
                          {stock.day_pct >= 0 ? '+' : ''}{stock.day_pct.toFixed(2)}%
                        </div>
                      </div>
                    </div>

                    {/* Score bar */}
                    <div style={{ display: 'flex', gap: '4px', marginBottom: '8px' }}>
                      {[1, 2, 3, 4, 5].map(n => (
                        <div
                          key={n}
                          style={{
                            flex: 1, height: '5px', borderRadius: '3px',
                            background: n <= stock.score
                              ? (stock.direction === 'BUY' ? '#4caf50' : stock.direction === 'SELL' ? '#ef4444' : '#6b7280')
                              : '#1e1e2e',
                          }}
                        />
                      ))}
                    </div>

                    {/* Indicators row */}
                    <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', fontSize: '0.65em' }}>
                      <span style={{ color: '#6b7280' }}>RSI <strong style={{ color: stock.rsi < 40 ? '#4caf50' : stock.rsi > 60 ? '#ef4444' : '#9ca3af' }}>{stock.rsi.toFixed(0)}</strong></span>
                      <span style={{ color: '#6b7280' }}>MACD <strong style={{ color: stock.macd === 'BUY' ? '#4caf50' : stock.macd === 'SELL' ? '#ef4444' : '#9ca3af' }}>{stock.macd}</strong></span>
                      <span style={{ color: '#6b7280' }}>ST <strong style={{ color: stock.supertrend === 'BULL' ? '#4caf50' : '#ef4444' }}>{stock.supertrend}</strong></span>
                      <span style={{ color: '#6b7280' }}>VWAP <strong style={{ color: stock.vwap === 'BUY' ? '#4caf50' : stock.vwap === 'SELL' ? '#ef4444' : '#9ca3af' }}>{stock.vwap}</strong></span>
                      {stock.vol_spike && <span style={{ color: '#fbbf24' }}>VOL SPIKE</span>}
                    </div>
                  </div>
                ))}
              </div>

              {sectorData.length === 0 && !sectorLoading && (
                <div style={{ color: '#4b5563', fontSize: '0.82em', marginTop: '20px', textAlign: 'center' }}>
                  Select a sector and click Refresh to load picks.
                </div>
              )}
              {sectorLoading && (
                <div style={{ color: '#6b7280', fontSize: '0.82em', marginTop: '20px', textAlign: 'center' }}>
                  Loading sector data...
                </div>
              )}
            </div>
          )}
        </div>

        {/* ── Bottom news ticker ──────────────────────────────────────────── */}
        {newsItems.length > 0 && (
          <div style={{
            borderTop: '1px solid #2a2a4a', background: '#0d0d1a', flexShrink: 0,
            padding: '4px 12px', overflow: 'hidden', whiteSpace: 'nowrap',
          }}>
            <div style={{ display: 'inline-flex', gap: '40px', animation: 'marquee 60s linear infinite', fontSize: '0.7em' }}>
              {newsItems.map((item, i) => (
                <span key={i} style={{ color: item.sentiment === 'BULLISH' ? '#4caf50' : item.sentiment === 'BEARISH' ? '#ef4444' : '#9ca3af' }}>
                  {item.title}
                </span>
              ))}
            </div>
          </div>
        )}
      </main>

      <style>{`
        @keyframes marquee {
          from { transform: translateX(100vw); }
          to   { transform: translateX(-300%); }
        }
        * { box-sizing: border-box; }
        ::-webkit-scrollbar { width: 5px; height: 5px; }
        ::-webkit-scrollbar-track { background: #0a0a14; }
        ::-webkit-scrollbar-thumb { background: #2a2a4a; border-radius: 3px; }
        select option { background: #12121f; }
      `}</style>
    </div>
  );
}
