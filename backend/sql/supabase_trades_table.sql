-- Run this in Supabase SQL Editor to create the trades + cooldown tables

-- Trades table
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
    status TEXT DEFAULT 'OPEN',
    created_at TEXT NOT NULL,
    exit_price REAL,
    exit_time TEXT,
    pnl REAL
);

-- Signal cooldown table (prevents duplicate signals)
CREATE TABLE IF NOT EXISTS signal_cooldown (
    instrument TEXT PRIMARY KEY,
    action TEXT NOT NULL,
    fired_at TEXT NOT NULL
);

-- Enable RLS
ALTER TABLE trades ENABLE ROW LEVEL SECURITY;
ALTER TABLE signal_cooldown ENABLE ROW LEVEL SECURITY;

-- Allow full access with service key
CREATE POLICY "Allow all on trades" ON trades FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all on signal_cooldown" ON signal_cooldown FOR ALL USING (true) WITH CHECK (true);
