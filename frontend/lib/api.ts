import type {
  AutoTraderConfig, AutoTraderState, AutoWatchRow, CandlesResponse, Health, IndexQuotes, LogKind, LogRow,
  NewsItem, OptionChainResponse, ScannerRow,
} from './types';

// Empty string = same origin (nginx proxies /api). Unset = local dev backend.
const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

export type ApiErrorKind = 'network' | 'timeout' | 'http' | 'parse' | 'aborted';

export class ApiError extends Error {
  constructor(message: string, readonly kind: ApiErrorKind, readonly status = 0) {
    super(message);
    this.name = 'ApiError';
  }
  /** True when retrying later might help (server busy / unreachable), false for "you sent something wrong". */
  get retryable() {
    return this.kind === 'network' || this.kind === 'timeout' || this.status === 502 || this.status === 503 || this.status === 504;
  }
}

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE';
  body?: unknown;
  signal?: AbortSignal;
  timeoutMs?: number;
  retries?: number; // extra attempts; defaults to 2 for GET, 0 for writes (never repeat an order/save)
}

const sleep = (ms: number) => new Promise(r => setTimeout(r, ms));

async function attempt<T>(path: string, opts: RequestOptions): Promise<T> {
  const controller = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => { timedOut = true; controller.abort(); }, opts.timeoutMs ?? 20000);
  const onAbort = () => controller.abort();
  opts.signal?.addEventListener('abort', onAbort);

  try {
    const res = await fetch(`${API_BASE}${path}`, {
      method: opts.method ?? 'GET',
      headers: opts.body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
      signal: controller.signal,
      cache: 'no-store',
    });

    let payload: unknown = null;
    const text = await res.text();
    if (text) {
      try { payload = JSON.parse(text); } catch { if (res.ok) throw new ApiError('Server sent an unreadable response', 'parse', res.status); }
    }

    if (!res.ok) {
      const detail = (payload as { detail?: unknown } | null)?.detail;
      const msg = typeof detail === 'string' ? detail : `Request failed (${res.status})`;
      throw new ApiError(msg, 'http', res.status);
    }
    return payload as T;
  } catch (e) {
    if (e instanceof ApiError) throw e;
    if (opts.signal?.aborted) throw new ApiError('Request cancelled', 'aborted');
    if (timedOut) throw new ApiError('The server took too long to respond', 'timeout');
    throw new ApiError('Cannot reach the server — check that the API is running', 'network');
  } finally {
    clearTimeout(timer);
    opts.signal?.removeEventListener('abort', onAbort);
  }
}

export async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const retries = opts.retries ?? ((opts.method ?? 'GET') === 'GET' ? 2 : 0);
  let lastErr: unknown;
  for (let i = 0; i <= retries; i++) {
    try {
      return await attempt<T>(path, opts);
    } catch (e) {
      lastErr = e;
      if (!(e instanceof ApiError) || !e.retryable || i === retries) break;
      await sleep(400 * 2 ** i);
      if (opts.signal?.aborted) throw new ApiError('Request cancelled', 'aborted');
    }
  }
  throw lastErr;
}

export function errorMessage(e: unknown): string {
  return e instanceof Error ? e.message : 'Something went wrong';
}

const q = encodeURIComponent;

export const api = {
  getHealth: (signal?: AbortSignal) => request<Health>('/api/health', { signal, retries: 0, timeoutMs: 8000 }),
  getIndices: (signal?: AbortSignal) => request<IndexQuotes>('/api/indices', { signal }),
  getNews: (signal?: AbortSignal) => request<NewsItem[]>('/api/news', { signal }),

  getScanner: (timeframe: string, signal?: AbortSignal) =>
    request<ScannerRow[]>(`/api/scanner?timeframe=${q(timeframe)}`, { signal, timeoutMs: 90000 }),
  getSectorPicks: (sector: string, timeframe: string, signal?: AbortSignal) =>
    request<ScannerRow[]>(`/api/sector-picks?sector=${q(sector)}&timeframe=${q(timeframe)}`, { signal, timeoutMs: 90000 }),
  getOptionChain: (symbol: string, signal?: AbortSignal) =>
    request<OptionChainResponse>(`/api/option-chain?symbol=${q(symbol)}`, { signal, timeoutMs: 40000 }),
  getFoSymbols: (signal?: AbortSignal) => request<string[]>('/api/fo-symbols', { signal, timeoutMs: 40000 }),
  getCandles: (symbol: string, timeframe: string, signal?: AbortSignal) =>
    request<CandlesResponse>(`/api/candles?symbol=${q(symbol)}&timeframe=${q(timeframe)}`, { signal, timeoutMs: 30000 }),

  getWatchlist: (signal?: AbortSignal) => request<string[]>('/api/watchlist', { signal }),
  addToWatchlist: (symbol: string) => request<{ success: boolean }>('/api/watchlist', { method: 'POST', body: { symbol } }),
  removeFromWatchlist: (symbol: string) => request<{ success: boolean }>(`/api/watchlist/${q(symbol)}`, { method: 'DELETE' }),

  getKiteLoginUrl: () => request<{ url: string }>('/api/kite/login-url', { retries: 1 }),
  kiteCallback: (requestToken: string) =>
    request<{ success: boolean }>('/api/kite/callback', { method: 'POST', body: { request_token: requestToken } }),

  // Auto trader
  getAutoState: (signal?: AbortSignal) => request<AutoTraderState>('/api/auto-trader/state', { signal, timeoutMs: 30000 }),
  saveAutoConfig: (changes: Partial<AutoTraderConfig>) =>
    request<AutoTraderConfig>('/api/auto-trader/config', { method: 'PUT', body: changes }),
  setAutoPaused: (paused: boolean) =>
    request<AutoTraderConfig>('/api/auto-trader/pause', { method: 'POST', body: { paused } }),
  exitPosition: (id: string) =>
    request<{ ok: boolean }>(`/api/auto-trader/positions/${q(id)}/exit`, { method: 'POST', timeoutMs: 45000 }),
  setAveragingPaused: (id: string, paused: boolean) =>
    request<{ ok: boolean }>(`/api/auto-trader/positions/${q(id)}/averaging`, { method: 'POST', body: { paused } }),
  getAutoLogs: (kinds: LogKind[], limit = 300, signal?: AbortSignal) =>
    request<LogRow[]>(`/api/auto-trader/logs?limit=${limit}${kinds.length ? `&kinds=${kinds.join(',')}` : ''}`, { signal }),
  getAutoWatchlist: (signal?: AbortSignal) =>
    request<AutoWatchRow[]>('/api/auto-trader/watchlist', { signal, timeoutMs: 90000 }),
};
