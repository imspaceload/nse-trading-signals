#!/bin/bash
# One-shot server setup: API (8000) + Next.js frontend (3000) + auto-trader worker, all as systemd services.
# Usage:  BRANCH=main bash setup.sh
set -e
BRANCH="${BRANCH:-main}"
REPO_DIR="/root/nse-trading-signals"
echo "=== NSE Trading Terminal — Setup (branch: $BRANCH) ==="

# Swap (small droplets run out of RAM during `next build`)
if [ ! -f /swapfile ]; then
  echo ">>> Adding 2GB swap..."
  fallocate -l 2G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

echo ">>> Installing system packages..."
apt update -qq && apt install -y python3-pip python3-venv git curl ufw nginx
if ! command -v node >/dev/null 2>&1; then
  curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
  apt install -y nodejs
fi

if [ -d "$REPO_DIR" ]; then
  echo ">>> Updating repo..."
  cd "$REPO_DIR"
  git fetch origin
  git checkout "$BRANCH"
  git pull origin "$BRANCH"
else
  echo ">>> Cloning repo..."
  git clone https://github.com/imspaceload/nse-trading-signals.git "$REPO_DIR"
  cd "$REPO_DIR"
  git checkout "$BRANCH"
fi
cd "$REPO_DIR"

echo ">>> Python environment..."
python3 -m venv venv
./venv/bin/pip install --upgrade pip -q
./venv/bin/pip install -r backend/requirements.txt -q

if [ ! -f .env ]; then
  cat > .env << 'ENVEOF'
KITE_API_KEY=
KITE_API_SECRET=
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_KEY=
FAST2SMS_API_KEY=
ENVEOF
  echo ">>> IMPORTANT: fill in $REPO_DIR/.env (nano .env), then: systemctl restart nse-api nse-autotrader"
fi

echo ">>> Frontend build..."
# Same-origin API/WS through nginx (see backend/deploy/nginx-snippet.conf)
printf 'NEXT_PUBLIC_API_URL=\nNEXT_PUBLIC_WS_URL=\n' > frontend/.env.production
(cd frontend && npm ci && npm run build)

echo ">>> systemd services..."
cp backend/deploy/nse-api.service /etc/systemd/system/nse-api.service
cp frontend/nse-frontend.service /etc/systemd/system/nse-frontend.service
cp backend/deploy/nse-autotrader.service /etc/systemd/system/nse-autotrader.service
systemctl daemon-reload
systemctl enable nse-api nse-frontend nse-autotrader
systemctl restart nse-api nse-frontend nse-autotrader

ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

echo ""
echo "Done. Add the nginx blocks from backend/deploy/nginx-snippet.conf to your site, then reload nginx."
echo "  Status:  systemctl status nse-api nse-frontend nse-autotrader"
echo "  Logs:    journalctl -u nse-api -f | journalctl -u nse-autotrader -f"
echo "  API keys: nano $REPO_DIR/.env   (then restart nse-api and nse-autotrader)"
