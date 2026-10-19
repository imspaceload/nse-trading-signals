export const SECTORS = [
  'Banking 🏦', 'IT / Tech 💻', 'Auto 🚗', 'Pharma 💊', 'FMCG 🛒', 'Metal & Mining ⛏',
  'Energy & Oil ⚡', 'Infrastructure 🏗', 'Telecom 📡', 'Consumer & Retail 🛍', 'Financial Services 📈',
] as const;

export const TIMEFRAMES = ['1m', '3m', '5m', '15m', '1h', '1D'] as const;
export const SCAN_TIMEFRAMES = ['5m', '15m', '1h', '1D'] as const;

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
