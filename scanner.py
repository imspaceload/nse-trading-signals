"""
Background scanner — runs via GitHub Actions every 2 min during market hours.
No Streamlit needed. Reuses existing modules for signal detection + SMS.
"""
import sys
import os
from datetime import datetime
import pytz

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import SYMBOLS, STOP_LOSS_PCT, TARGET_PCT
from data_fetcher import (
    get_spot_price, get_intraday_data, get_option_chain_data,
    get_option_recommendation, is_market_open, get_current_option_ltp,
)
from indicators import (
    compute_rsi, compute_macd, compute_supertrend, compute_vwap,
    evaluate_oi, generate_signal,
)
from trades import create_trade, close_trade, get_open_trades
from sms_sender import send_sms_to_all

IST = pytz.timezone("Asia/Kolkata")

# ── Cooldown: use Supabase to persist last signal time per instrument ──

def _get_supabase():
    from sms_sender import _get_supabase as sb_func
    return sb_func()


def _get_last_signal(instrument: str) -> dict:
    """Get last signal info from Supabase cooldown table."""
    sb = _get_supabase()
    if not sb:
        return {}
    try:
        resp = sb.table("signal_cooldown").select("*").eq("instrument", instrument).execute()
        return resp.data[0] if resp.data else {}
    except Exception:
        return {}


def _set_last_signal(instrument: str, action: str):
    """Update cooldown record in Supabase."""
    sb = _get_supabase()
    if not sb:
        return
    now = datetime.now(IST).isoformat()
    try:
        existing = sb.table("signal_cooldown").select("instrument").eq("instrument", instrument).execute()
        if existing.data:
            sb.table("signal_cooldown").update({
                "action": action,
                "fired_at": now,
            }).eq("instrument", instrument).execute()
        else:
            sb.table("signal_cooldown").insert({
                "instrument": instrument,
                "action": action,
                "fired_at": now,
            }).execute()
    except Exception as e:
        print(f"  [!] Cooldown update failed: {e}")


def scan_symbol(name: str, sym_info: dict):
    """Scan one symbol for signals, auto-trade + SMS if triggered."""
    yf_sym = sym_info["yf"]
    nse_sym = sym_info["nse"]

    # Fetch data
    spot = get_spot_price(yf_sym)
    if spot is None:
        print(f"  [!] Could not fetch spot price for {name}")
        return

    df = get_intraday_data(yf_sym, period="5d", interval="5m")
    if df.empty:
        print(f"  [!] No intraday data for {name}")
        return

    oi_data = None
    if nse_sym:
        try:
            oi_data = get_option_chain_data(nse_sym)
        except Exception:
            pass

    # Compute indicators
    rsi = compute_rsi(df)
    macd = compute_macd(df)
    st_data = compute_supertrend(df)
    vwap = compute_vwap(df)
    oi = evaluate_oi(oi_data)
    signal = generate_signal(rsi, macd, st_data, vwap, oi, spot)

    action = signal["action"]
    print(f"  Signal: {action} | RSI={rsi['value']} | MACD={macd['signal_text']} | ST={st_data['trend']}")

    if action not in ("BUY", "SELL"):
        return

    # Check cooldown (15 min)
    last = _get_last_signal(name)
    if last:
        last_action = last.get("action", "")
        last_time = last.get("fired_at", "")
        if last_action == action and last_time:
            try:
                fired = datetime.fromisoformat(last_time)
                if fired.tzinfo is None:
                    fired = IST.localize(fired)
                elapsed = (datetime.now(IST) - fired).total_seconds()
                if elapsed < 900:
                    print(f"  [~] Cooldown active ({int(900 - elapsed)}s left), skipping")
                    return
            except Exception:
                pass

    # Get option recommendation
    opt = None
    if nse_sym:
        try:
            opt = get_option_recommendation(nse_sym, spot, action)
        except Exception:
            pass

    opt_type = "CE" if action == "BUY" else "PE"

    if opt:
        trade = create_trade(
            instrument=name,
            strike=opt["strike"],
            option_type=opt_type,
            expiry=opt["expiry"],
            entry_price=opt["ltp"],
            target_price=opt["premium_target"],
            stop_loss=opt["premium_sl"],
            quantity=1,
            lot_size=opt["lot_size"],
        )
    else:
        trade = create_trade(
            instrument=name,
            strike=round(spot / 100) * 100,
            option_type=opt_type,
            expiry="Weekly",
            entry_price=spot,
            target_price=signal["target"] if signal["target"] else round(spot * 1.01, 2),
            stop_loss=signal["stop_loss"] if signal["stop_loss"] else round(spot * 0.997, 2),
            quantity=1,
            lot_size=1,
        )

    print(f"  ✅ Trade created: {trade['instrument']} {trade['strike']}{opt_type} @ Rs{trade['entry_price']}")

    # Send SMS
    results = send_sms_to_all(trade, action="BUY")
    sent = sum(1 for r in results if r.get("status") != "failed")
    print(f"  📱 SMS sent to {sent} subscriber(s)")

    # Update cooldown
    _set_last_signal(name, action)


def check_auto_close():
    """Check all open trades for SL/target hit."""
    open_trades = get_open_trades()
    if not open_trades:
        return

    print(f"\n── Checking {len(open_trades)} open trade(s) for SL/Target ──")
    for t in open_trades:
        sym_info = SYMBOLS.get(t["instrument"], {})
        nse_sym = sym_info.get("nse", "")
        if not nse_sym:
            continue

        current_ltp = get_current_option_ltp(
            nse_sym, t["strike"], t["option_type"], t["expiry"]
        )
        if current_ltp is None:
            print(f"  [!] Could not fetch LTP for {t['instrument']} {t['strike']}{t['option_type']}")
            continue

        print(f"  {t['instrument']} {t['strike']}{t['option_type']}: LTP={current_ltp} | SL={t['stop_loss']} | T={t['target_price']}")

        if t["stop_loss"] > 0 and current_ltp <= t["stop_loss"]:
            closed = close_trade(t["id"], current_ltp)
            if closed:
                print(f"  🛑 SL HIT — closed at Rs{current_ltp}, P&L: {closed['pnl']}")
                send_sms_to_all(closed, action="EXIT")
        elif t["target_price"] > 0 and current_ltp >= t["target_price"]:
            closed = close_trade(t["id"], current_ltp)
            if closed:
                print(f"  🎯 TARGET HIT — closed at Rs{current_ltp}, P&L: {closed['pnl']}")
                send_sms_to_all(closed, action="EXIT")


def main():
    now = datetime.now(IST)
    print(f"\n{'='*50}")
    print(f"Scanner run: {now.strftime('%Y-%m-%d %H:%M:%S IST')}")
    print(f"{'='*50}")

    if not is_market_open():
        print("Market is closed. Exiting.")
        return

    # Scan key symbols (NIFTY + BANKNIFTY by default, add more as needed)
    scan_list = ["NIFTY 50", "BANK NIFTY"]

    for name in scan_list:
        sym_info = SYMBOLS.get(name)
        if not sym_info:
            continue
        print(f"\n── Scanning {name} ──")
        try:
            scan_symbol(name, sym_info)
        except Exception as e:
            print(f"  [!] Error scanning {name}: {e}")

    # Check open trades for auto-close
    try:
        check_auto_close()
    except Exception as e:
        print(f"  [!] Error in auto-close: {e}")

    print(f"\n{'='*50}")
    print("Scanner complete.")


if __name__ == "__main__":
    main()
