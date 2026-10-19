-- Every table the app uses, for a fresh Supabase project.
-- Paste the whole file into Supabase → SQL Editor → Run. Safe to re-run.

-- ── Key/value store: Kite access token + login date, worker heartbeat ──
CREATE TABLE IF NOT EXISTS config (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TEXT
);

-- ── Auto-trader ──
CREATE TABLE IF NOT EXISTS auto_trader_config (
    id INTEGER PRIMARY KEY DEFAULT 1,
    total_capital REAL DEFAULT 100000,
    max_margin_pct REAL DEFAULT 20,
    max_active_trades INTEGER DEFAULT 2,
    max_trades_per_day INTEGER DEFAULT 3,
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
-- Existing projects: columns added after the table was first created
ALTER TABLE auto_trader_config ADD COLUMN IF NOT EXISTS max_trades_per_day INTEGER DEFAULT 3;
ALTER TABLE auto_trader_config ADD COLUMN IF NOT EXISTS stop_loss_action TEXT DEFAULT 'EXIT';
ALTER TABLE auto_trader_config ADD COLUMN IF NOT EXISTS lots_per_trade INTEGER DEFAULT 1;
ALTER TABLE auto_trader_config ADD COLUMN IF NOT EXISTS product TEXT DEFAULT 'NRML';
ALTER TABLE auto_trader_config ADD COLUMN IF NOT EXISTS square_off_eod BOOLEAN DEFAULT TRUE;
INSERT INTO auto_trader_config (id) VALUES (1) ON CONFLICT (id) DO NOTHING;

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
    exit_reason TEXT
);

CREATE TABLE IF NOT EXISTS auto_trader_logs (
    id BIGSERIAL PRIMARY KEY,
    at TEXT NOT NULL,
    kind TEXT NOT NULL,                -- ENTERED | EXIT | AVERAGED | SKIP | FAILED | ERROR
    symbol TEXT,
    message TEXT
);
CREATE INDEX IF NOT EXISTS auto_trader_logs_at_idx ON auto_trader_logs (at DESC);

-- ── SMS alert jobs ──
CREATE TABLE IF NOT EXISTS trades (
    id TEXT PRIMARY KEY,
    instrument TEXT NOT NULL,
    strike REAL NOT NULL,
    option_type TEXT NOT NULL,
    expiry TEXT NOT NULL,
    entry_price REAL NOT NULL,
    target_price REAL NOT NULL,
    stop_loss REAL NOT NULL,
    quantity INTEGER DEFAULT 1,
    lot_size INTEGER DEFAULT 1,
    averaging_price REAL,
    status TEXT DEFAULT 'OPEN',
    created_at TEXT NOT NULL,
    exit_price REAL,
    exit_time TEXT,
    pnl REAL
);

CREATE TABLE IF NOT EXISTS signal_cooldown (   -- prevents duplicate signals
    instrument TEXT PRIMARY KEY,
    action TEXT NOT NULL,
    fired_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS subscribers (
    phone TEXT PRIMARY KEY,
    name TEXT,
    added TEXT,
    active BOOLEAN DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS sms_log (
    id BIGSERIAL PRIMARY KEY,
    phone TEXT,
    message TEXT,
    status TEXT,
    error TEXT,
    request_id TEXT,
    api_response TEXT,
    timestamp TEXT
);

-- ── Dashboard watchlist ──
CREATE TABLE IF NOT EXISTS watchlist (
    symbol TEXT PRIMARY KEY,
    added_at TEXT
);

-- ── Row-level security: the backend uses the publishable key, so allow it full access ──
DO $$
DECLARE t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['config', 'auto_trader_config', 'auto_trader_positions', 'auto_trader_logs',
                             'trades', 'signal_cooldown', 'subscribers', 'sms_log', 'watchlist'] LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('DROP POLICY IF EXISTS "Allow all on %s" ON %I', t, t);
        EXECUTE format('CREATE POLICY "Allow all on %s" ON %I FOR ALL USING (true) WITH CHECK (true)', t, t);
    END LOOP;
END $$;
