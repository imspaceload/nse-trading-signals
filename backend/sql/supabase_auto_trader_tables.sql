-- Run this in Supabase SQL Editor to create the Auto Trader (Module A) tables.
-- Safe to run even if you already have the `trades` / `signal_cooldown` tables
-- from supabase_trades_table.sql — this only adds two new tables.

-- Singleton config row (id is always 1)
CREATE TABLE IF NOT EXISTS auto_trader_config (
    id INTEGER PRIMARY KEY DEFAULT 1,
    total_capital REAL DEFAULT 100000,
    max_margin_pct REAL DEFAULT 20,
    max_active_trades INTEGER DEFAULT 2,
    profit_target_pct REAL DEFAULT 10,
    averaging_drop_pct REAL DEFAULT 5,
    max_averaging_rounds INTEGER DEFAULT 3,
    trade_mode TEXT DEFAULT 'OPTIONS',
    trade_paused BOOLEAN DEFAULT FALSE,
    min_entry_score INTEGER DEFAULT 3,
    stop_loss_pct REAL DEFAULT 10,
    stop_loss_action TEXT DEFAULT 'EXIT',
    lots_per_trade INTEGER DEFAULT 1,
    product TEXT DEFAULT 'NRML',
    square_off_eod BOOLEAN DEFAULT TRUE
);

-- Existing installs: add the newer column
ALTER TABLE auto_trader_config ADD COLUMN IF NOT EXISTS min_entry_score INTEGER DEFAULT 3;
ALTER TABLE auto_trader_config ADD COLUMN IF NOT EXISTS stop_loss_pct REAL DEFAULT 10;
ALTER TABLE auto_trader_config ADD COLUMN IF NOT EXISTS max_trades_per_day INTEGER DEFAULT 3;
ALTER TABLE auto_trader_config ADD COLUMN IF NOT EXISTS stop_loss_action TEXT DEFAULT 'EXIT';
ALTER TABLE auto_trader_config ADD COLUMN IF NOT EXISTS lots_per_trade INTEGER DEFAULT 1;
ALTER TABLE auto_trader_config ADD COLUMN IF NOT EXISTS product TEXT DEFAULT 'NRML';
ALTER TABLE auto_trader_config ADD COLUMN IF NOT EXISTS square_off_eod BOOLEAN DEFAULT TRUE;

-- Positions (open + closed) managed by the auto-trader engine
CREATE TABLE IF NOT EXISTS auto_trader_positions (
    id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,              -- NSE underlying symbol, e.g. RELIANCE
    exchange TEXT NOT NULL,            -- NFO | NSE
    trade_mode TEXT NOT NULL,          -- OPTIONS | EQUITY
    option_type TEXT,                  -- CE | PE | NULL (equity mode)
    tradingsymbol TEXT NOT NULL,       -- actual Kite tradingsymbol traded
    instrument_token BIGINT,
    qty_per_round INTEGER NOT NULL,
    total_qty INTEGER NOT NULL,
    entry_price REAL NOT NULL,
    avg_price REAL NOT NULL,
    current_price REAL,
    rounds INTEGER DEFAULT 1,
    status TEXT DEFAULT 'OPEN',        -- OPEN | CLOSED
    paused_averaging BOOLEAN DEFAULT FALSE,
    last_order_at TEXT,
    pnl REAL DEFAULT 0,
    pnl_pct REAL DEFAULT 0,
    orders JSONB DEFAULT '[]',         -- [{order_id, side, qty, price, round, at}, ...]
    created_at TEXT NOT NULL,
    closed_at TEXT,
    exit_reason TEXT                   -- profit_target | manual
);

ALTER TABLE auto_trader_config ENABLE ROW LEVEL SECURITY;
ALTER TABLE auto_trader_positions ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Allow all on auto_trader_config" ON auto_trader_config FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all on auto_trader_positions" ON auto_trader_positions FOR ALL USING (true) WITH CHECK (true);

-- Seed the singleton config row with defaults (no-op if it already exists)
INSERT INTO auto_trader_config (id) VALUES (1) ON CONFLICT (id) DO NOTHING;

-- Activity log (ENTERED / EXIT / AVERAGED / SKIP / FAILED / ERROR) shown in the dashboard
CREATE TABLE IF NOT EXISTS auto_trader_logs (
    id BIGSERIAL PRIMARY KEY,
    at TEXT NOT NULL,
    kind TEXT NOT NULL,
    symbol TEXT,
    message TEXT
);
ALTER TABLE auto_trader_logs ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Allow all on auto_trader_logs" ON auto_trader_logs FOR ALL USING (true) WITH CHECK (true);
