#!/bin/bash
# Adds /api/ proxy to nginx so the chart iframe can call FastAPI (port 8000)
# Run this ONCE on the server: sudo bash scripts/expose-api-nginx.sh
set -e

NGINX_CONF="/etc/nginx/sites-available/rstrades"

echo "=== Exposing FastAPI under /api/ ==="

cp "$NGINX_CONF" "${NGINX_CONF}.bak.$(date +%Y%m%d%H%M%S)"
echo "Backed up nginx config"

python3 - <<'PYEOF'
import re, sys

path = '/etc/nginx/sites-available/rstrades'
with open(path) as f:
    content = f.read()

api_block = '''    location /api/ {
        proxy_pass http://127.0.0.1:8000/api/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        add_header 'Access-Control-Allow-Origin' '*' always;
    }

'''

if 'location /api/' in content:
    print("INFO: /api/ block already exists in nginx config — skipping.")
    sys.exit(0)

# Insert before location /
new_content = content.replace('    location / {', api_block + '    location / {', 1)
if new_content == content:
    print("ERROR: Could not find 'location /' block to insert before.")
    sys.exit(1)

with open(path, 'w') as f:
    f.write(new_content)
print("Added /api/ proxy block pointing to FastAPI on port 8000")
PYEOF

echo "Testing nginx config..."
nginx -t

echo "Reloading nginx..."
systemctl reload nginx

echo ""
echo "=== Checking nse-api service ==="
systemctl is-active nse-api || systemctl start nse-api
systemctl status nse-api --no-pager | tail -5

echo ""
echo "Done! Chart iframe can now call /api/live/ltp and /api/live/candles"
echo "Prices will update every 1 second inside the chart without page reload."
