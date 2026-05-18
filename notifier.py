"""Signal formatting + email notification helpers."""
from datetime import datetime
from typing import Optional
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import pytz

IST = pytz.timezone("Asia/Kolkata")


def format_signal_chat(signal_data: dict, symbol: str, analysis: str = "") -> str:
    action = signal_data["action"]
    if action == "BUY":
        return f"""🟢 <b>BUY {symbol}</b><br>
📍 Buy at ₹{signal_data['entry_price']:,.2f} → Buy CE<br>
🛑 Stop Loss: ₹{signal_data['stop_loss']:,.2f}<br>
🎯 Target: ₹{signal_data['target']:,.2f}<br>
{'💡 ' + analysis if analysis else ''}"""
    elif action == "SELL":
        return f"""🔴 <b>SELL {symbol}</b><br>
📍 Sell at ₹{signal_data['entry_price']:,.2f} → Buy PE<br>
🛑 Stop Loss: ₹{signal_data['stop_loss']:,.2f}<br>
🎯 Target: ₹{signal_data['target']:,.2f}<br>
{'💡 ' + analysis if analysis else ''}"""
    else:
        return f"""🟡 <b>HOLD — {symbol}</b><br>
⏸️ No clear signal. Don't trade when unsure."""


def send_signal_email(
    sender_email: str,
    sender_password: str,
    receiver_email: str,
    symbol: str,
    signal_data: dict,
    option_rec: Optional[dict] = None,
) -> bool:
    """Send an email alert when a BUY/SELL signal fires.

    Uses Gmail SMTP. Sender needs a Gmail App Password (not regular password).
    """
    action = signal_data["action"]
    if action not in ("BUY", "SELL"):
        return False

    now = datetime.now(IST).strftime("%I:%M %p, %d %b %Y")
    opt_type = "CE (Call)" if action == "BUY" else "PE (Put)"
    emoji = "🟢" if action == "BUY" else "🔴"

    subject = f"{emoji} {action} Signal — {symbol} @ ₹{signal_data['entry_price']:,.2f}"

    # Build the email body
    body = f"""
    <html><body style="font-family: -apple-system, Arial, sans-serif; background: #0f0f1a; color: #e5e7eb; padding: 20px;">
    <div style="max-width: 500px; margin: 0 auto;">

    <div style="background: {'#065f46' if action == 'BUY' else '#991b1b'}; padding: 20px; border-radius: 12px; margin-bottom: 16px;">
        <h1 style="margin: 0; color: white; font-size: 24px;">{emoji} {action} {symbol}</h1>
        <p style="color: rgba(255,255,255,0.8); margin: 8px 0 0 0; font-size: 14px;">{now}</p>
    </div>

    <div style="background: #1e1e2e; padding: 16px; border-radius: 10px; margin-bottom: 12px;">
        <h3 style="color: #94a3b8; margin: 0 0 12px 0;">📌 What to do:</h3>
        <p style="color: #fbbf24; font-size: 16px; margin: 8px 0;">Buy <b>{opt_type}</b></p>
        <p style="color: #e5e7eb; margin: 6px 0;">📍 Entry Price: <b>₹{signal_data['entry_price']:,.2f}</b></p>
        <p style="color: #e5e7eb; margin: 6px 0;">🛑 Stop Loss: <b>₹{signal_data['stop_loss']:,.2f}</b></p>
        <p style="color: #e5e7eb; margin: 6px 0;">🎯 Target: <b>₹{signal_data['target']:,.2f}</b></p>
    </div>
    """

    if option_rec:
        body += f"""
    <div style="background: #1a1a2e; padding: 16px; border-radius: 10px; border: 1px solid #6366f1; margin-bottom: 12px;">
        <h3 style="color: #a5b4fc; margin: 0 0 10px 0;">📋 Option Contract</h3>
        <p style="color: #22d3ee; font-size: 20px; font-weight: 800; margin: 6px 0;">{option_rec['contract']}</p>
        <p style="color: #cbd5e1; margin: 4px 0;">Expiry: <b>{option_rec['expiry']}</b></p>
        <p style="color: #cbd5e1; margin: 4px 0;">Premium: <b>₹{option_rec['ltp']:,.2f}</b></p>
        <p style="color: #cbd5e1; margin: 4px 0;">Lot Size: <b>{option_rec['lot_size']}</b> | Total Cost: <b>₹{option_rec['total_premium']:,.2f}</b></p>
        <p style="color: #fbbf24; margin: 8px 0; font-weight: 700;">🛑 Premium SL: ₹{option_rec['premium_sl']:,.2f} | 🎯 Target: ₹{option_rec['premium_target']:,.2f}</p>
    </div>
    """

    body += """
    <div style="background: #1e1e2e; padding: 12px; border-radius: 8px;">
        <p style="color: #6b7280; font-size: 12px; margin: 0;">⚠️ For educational purposes only. Not financial advice. Always use stop loss.</p>
    </div>

    </div></body></html>
    """

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = sender_email
        msg["To"] = receiver_email
        msg.attach(MIMEText(body, "html"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, receiver_email, msg.as_string())
        return True
    except Exception as e:
        print(f"Email send failed: {e}")
        return False
