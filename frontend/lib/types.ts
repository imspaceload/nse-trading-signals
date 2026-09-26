export type Direction = 'BUY' | 'SELL' | 'NEUTRAL';

export interface ScannerRow {
  symbol: string;
  spot: number;
  score: number;
  direction: Direction;
  rsi: number;
  macd: string;
  supertrend: 'BULL' | 'BEAR';
  vwap: string;
  vol_spike: boolean;
  day_pct: number;
}

export interface OptionLeg {
  lastPrice?: number;
  openInterest?: number;
  impliedVolatility?: number;
  totalTradedVolume?: number;
}

export interface OptionRow {
  strikePrice: number;
  expiryDate?: string;
  CE?: OptionLeg;
  PE?: OptionLeg;
}

export interface OptionChainResponse {
  records?: {
    data?: OptionRow[];
    expiryDates?: string[];
    underlyingValue?: number;
  };
}

export interface NewsItem {
  title?: string;
  headline?: string;
  url?: string;
  sentiment?: string;
}

export interface Candle {
  time: number; // UTC epoch seconds
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface CandlesResponse {
  symbol: string;
  timeframe: string;
  /** 'kite' = live from Zerodha, 'yahoo' = delayed fallback when logged out or not on NSE. */
  source: 'kite' | 'yahoo';
  candles: Candle[];
}

export type PivotKey = 'R2' | 'R1' | 'PP' | 'S1' | 'S2';

/** The auto-trader's view of one symbol (15m score) plus previous-session pivots for the chart. */
export interface ChartSignal {
  symbol: string;
  timeframe: string;
  source: 'kite' | 'yahoo';
  spot: number;
  direction: Direction;
  score: number;
  buy_pts: number;
  sell_pts: number;
  rsi: number;
  macd: string;
  supertrend: 'BULL' | 'BEAR';
  vwap: string;
  vol_spike: boolean;
  pivots: Record<PivotKey, number>;
  levels: { T1: number; T2: number; AVG: number; SL1: number; SL2: number | null };
  /** null when the symbol has no NSE options (commodities, SENSEX). */
  option: { underlying: string; atm: number; ce_trigger: number; ce_strike: number; pe_trigger: number; pe_strike: number } | null;
  session: { open: number; high: number; low: number };
  auto_trader: { scanned: boolean; sector: string | null; min_score: number };
}

export interface Quote {
  ltp: number;
  pct: number;
  change: number;
}

export interface Health {
  status: string;
  kite_connected: boolean;
  kite_configured?: boolean;
  market_open?: boolean;
  server_time?: string;
}

export type IndexQuotes = Record<string, { price: number; pct: number; change: number }>;

// ── Auto trader ─────────────────────────────────────────────────────────────

export interface AutoTraderConfig {
  total_capital: number;
  max_margin_pct: number;
  max_active_trades: number;
  max_trades_per_day: number;
  profit_target_pct: number;
  averaging_drop_pct: number;
  max_averaging_rounds: number;
  trade_mode: 'OPTIONS' | 'EQUITY';
  trade_paused: boolean;
  min_entry_score: number;
  stop_loss_pct: number;
  stop_loss_action: 'EXIT' | 'AVERAGE';
}

export interface AutoPosition {
  id: string;
  symbol: string;
  tradingsymbol: string;
  exchange: string;
  trade_mode: string;
  option_type: string | null;
  qty_per_round: number;
  total_qty: number;
  entry_price: number;
  avg_price: number;
  current_price: number | null;
  rounds: number;
  status: 'OPEN' | 'CLOSED';
  paused_averaging: boolean;
  pnl: number | null;
  pnl_pct: number | null;
  created_at: string;
  closed_at: string | null;
  exit_reason: string | null;
}

export interface AutoSummary {
  total_capital: number;
  deployed: number;
  available: number;
  available_is_live: boolean;
  pnl_today: number;
  open_count: number;
  max_active_trades: number;
}

export interface AutoTraderState {
  config: AutoTraderConfig;
  summary: AutoSummary;
  positions: AutoPosition[];
  closed: AutoPosition[];
  worker: { alive: boolean; status: string | null; age_seconds: number | null; watchlist: number | null };
  market_open: boolean;
  kite_connected: boolean;
  trades_today: number;
  rules: { entry_cutoff: string; square_off: string; exit_cooldown_seconds: number };
  warnings: string[];
}

export type LogKind = 'ENTERED' | 'EXIT' | 'AVERAGED' | 'SKIP' | 'FAILED' | 'ERROR';

export interface LogRow {
  id?: number;
  at: string;
  kind: LogKind;
  symbol: string;
  message: string;
}

export interface AutoWatchRow {
  symbol: string;
  signal: 'BUY' | 'SELL';
  side: 'CE' | 'PE';
  spot: number;
  score: number;
  sector: string;
  rsi: number;
  day_pct: number;
  eligible: boolean;
}
