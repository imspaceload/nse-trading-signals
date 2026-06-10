#!/bin/bash
# Reverts nginx to serve the old Streamlit UI (port 8501) instead of Next.js (port 3000)
set -e

NGINX_CONF="/etc/nginx/sites-available/rstrades"

echo "=== Reverting to Streamlit UI ==="

# Backup current nginx config
cp "$NGINX_CONF" "${NGINX_CONF}.bak.$(date +%Y%m%d%H%M%S)"
echo "Backed up nginx config"

# Use Python to safely replace only the location / block (preserves SSL blocks certbot added)
python3 - <<'PYEOF'
import re, sys

path = '/etc/nginx/sites-available/rstrades'
with open(path) as f:
    content = f.read()

# Replace the Next.js location / block with a Streamlit one (with WebSocket support)
# Handles both with and without existing ws upgrade headers
pattern = r'(location / \{)[^}]*(proxy_pass http://127\.0\.0\.1:3000;)[^}]*(\})'
replacement = r'''\1
        proxy_pass http://127.0.0.1:8501;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    \3'''

new_content, n = re.subn(pattern, replacement, content, flags=re.DOTALL)
if n == 0:
    print("ERROR: Could not find 'proxy_pass http://127.0.0.1:3000' in nginx config.")
    print("Current location / block in your config:")
    block = re.search(r'location / \{[^}]*\}', content, re.DOTALL)
    if block:
        print(block.group())
    else:
        print("(no location / block found)")
    sys.exit(1)

with open(path, 'w') as f:
    f.write(new_content)
print(f"Updated {n} location block(s) to point to Streamlit on port 8501")
PYEOF

# Test and reload nginx
echo "Testing nginx config..."
nginx -t

echo "Reloading nginx..."
systemctl reload nginx

# Start and enable Streamlit service
echo "Starting Streamlit service (nse-trading)..."
systemctl enable nse-trading 2>/dev/null || true
systemctl restart nse-trading

sleep 2

echo ""
echo "=== Status ==="
systemctl status nse-trading --no-pager | tail -8

echo ""
echo "✓ Done! Streamlit UI is now live at https://rstrades.in"
echo "  (Next.js service is still running on port 3000 but nginx no longer routes to it)"
