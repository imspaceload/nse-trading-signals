export const SECTORS = [
  'Banking 🏦', 'IT / Tech 💻', 'Auto 🚗', 'Pharma 💊', 'FMCG 🛒', 'Metal & Mining ⛏',
  'Energy & Oil ⚡', 'Infrastructure 🏗', 'Telecom 📡', 'Consumer & Retail 🛍', 'Financial Services 📈',
] as const;

export const TIMEFRAMES = ['1m', '3m', '5m', '15m', '1h', '1D'] as const;
export const SCAN_TIMEFRAMES = ['5m', '15m', '1h', '1D'] as const;

const TV_SYMBOL: Record<string, string> = {
  'NIFTY 50': 'NSE:NIFTY',
  'BANK NIFTY': 'NSE:BANKNIFTY',
  'FIN NIFTY': 'NSE:FINNIFTY',
  'SENSEX': 'BSE:SENSEX',
  'INDIA VIX': 'NSE:INDIAVIX',
};
export const TV_INTERVAL: Record<string, string> = { '1m': '1', '3m': '3', '5m': '5', '15m': '15', '1h': '60', '1D': 'D' };

export function toTvSymbol(sym: string): string {
  return TV_SYMBOL[sym] ?? `NSE:${sym.replace(/[^A-Z0-9&-]/gi, '').toUpperCase()}`;
}

export const DEFAULT_WATCHLIST = ['NIFTY 50', 'BANK NIFTY', 'RELIANCE', 'HDFCBANK', 'TCS', 'INFY'];

export const TABS = [
  { key: 'chart', label: '📈 Chart' },
  { key: 'optionchain', label: '⛓ Option Chain' },
  { key: 'scanner', label: '📊 Scanner' },
  { key: 'sectorpicks', label: '🎯 Sector Picks' },
  { key: 'autotrader', label: '🤖 Auto Trader' },
  { key: 'autolog', label: '📜 Auto Trade Log' },
] as const;

export type TabKey = (typeof TABS)[number]['key'];
export const isTabKey = (v: unknown): v is TabKey => TABS.some(t => t.key === v);
