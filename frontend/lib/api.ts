const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export const api = {
  getQuotes: (symbols: string[]) =>
    fetch(`${API_BASE}/api/quotes?symbols=${symbols.join(',')}`).then(r => r.json()),

  getChart: (symbol: string, timeframe: string) =>
    fetch(`${API_BASE}/api/chart?symbol=${symbol}&timeframe=${timeframe}`).then(r => r.json()),

  getScanner: (timeframe: string) =>
    fetch(`${API_BASE}/api/scanner?timeframe=${timeframe}`).then(r => r.json()),

  getSectorPicks: (sector: string, timeframe: string) =>
    fetch(`${API_BASE}/api/sector-picks?sector=${encodeURIComponent(sector)}&timeframe=${timeframe}`).then(r => r.json()),

  getOptionChain: (symbol: string) =>
    fetch(`${API_BASE}/api/option-chain?symbol=${symbol}`).then(r => r.json()),

  getWatchlist: () =>
    fetch(`${API_BASE}/api/watchlist`).then(r => r.json()),

  addToWatchlist: (symbol: string) =>
    fetch(`${API_BASE}/api/watchlist`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ symbol }),
    }).then(r => r.json()),

  removeFromWatchlist: (symbol: string) =>
    fetch(`${API_BASE}/api/watchlist/${symbol}`, { method: 'DELETE' }).then(r => r.json()),

  getIndices: () =>
    fetch(`${API_BASE}/api/indices`).then(r => r.json()),

  getHealth: () =>
    fetch(`${API_BASE}/api/health`).then(r => r.json()),

  getNews: () =>
    fetch(`${API_BASE}/api/news`).then(r => r.json()),

  getKiteLoginUrl: () =>
    fetch(`${API_BASE}/api/kite/login-url`).then(r => r.json()),
};
