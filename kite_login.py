#!/usr/bin/env python3
"""
Daily Zerodha Kite Connect token refresh.
Run each morning before market opens:

    cd /root/nse-trading-signals
    python kite_login.py
"""
import os
import sys

# Load .env BEFORE importing zerodha_api so module-level KITE_API_SECRET is populated.
_ENV_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(_ENV_FILE):
    with open(_ENV_FILE) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _, _v = _line.partition("=")
                os.environ.setdefault(_k.strip(), _v.strip())

from kite_api import get_login_url, complete_login


def main():
    url = get_login_url()
    if not url:
        print("ERROR: KITE_API_KEY is not set.\n")
        print(f"Add your credentials to {_ENV_FILE}:")
        print("  KITE_API_KEY=<your api key>")
        print("  KITE_API_SECRET=<your api secret>")
        sys.exit(1)

    print("=" * 55)
    print("  Zerodha Kite Connect — Daily Token Refresh")
    print("=" * 55)
    print()
    print("Step 1: Open this URL in your browser:\n")
    print(f"  {url}\n")
    print("Step 2: Log in with your Zerodha credentials.")
    print("        After login you'll land on a URL like:\n")
    print("  http://127.0.0.1/?request_token=XXXXX&action=login&status=success\n")
    print("Step 3: Copy the value after 'request_token=' from that URL.\n")

    try:
        token = input("Paste request_token here: ").strip()
    except (KeyboardInterrupt, EOFError):
        print("\nAborted.")
        sys.exit(1)

    if not token:
        print("No token entered. Exiting.")
        sys.exit(1)

    print("\nExchanging token with Zerodha...")
    access_token = complete_login(token)

    if access_token:
        print(f"\n[OK] Login successful!")
        print(f"     Token saved to kite_token.txt and kite_token.json")
        print(f"     Preview: {access_token[:12]}...")
        print("\nThe app picks up the new token automatically on next option-chain load.")
        print("To apply immediately, restart the service:")
        print("  systemctl restart nse-trading.service")
    else:
        print("\n[FAIL] Login failed.")
        print("       Verify KITE_API_KEY and KITE_API_SECRET in .env, then retry.")
        sys.exit(1)


if __name__ == "__main__":
    main()
