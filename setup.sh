#!/bin/bash
set -e
echo "=== NSE Trading Signals — Auto Setup ==="

# Add swap (512MB RAM needs this)
if [ ! -f /swapfile ]; then
  echo ">>> Adding 1GB swap..."
  fallocate -l 1G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

# System deps
echo ">>> Installing system packages..."
apt update -qq && apt install -y python3-pip python3-venv git curl ufw

# Clone or update repo
REPO_DIR="/root/nse-trading-signals"
if [ -d "$REPO_DIR" ]; then
  echo ">>> Updating repo..."
  cd "$REPO_DIR"
  git fetch origin
  git checkout claude/stocks-unavailable-e9l41
  git pull origin claude/stocks-unavailable-e9l41
else
  echo ">>> Cloning repo..."
  git clone https://github.com/imspaceload/nse-trading-signals.git "$REPO_DIR"
  cd "$REPO_DIR"
  git checkout claude/stocks-unavailable-e9l41
fi

cd "$REPO_DIR"

# Python venv
echo ">>> Setting up Python environment..."
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip -q
pip install -r requirements.txt -q

# Create .env if not exists
if [ ! -f "$REPO_DIR/.env" ]; then
  echo ">>> Creating .env template..."
  cat > "$REPO_DIR/.env" << 'EOF'
ANTHROPIC_API_KEY=
DHAN_CLIENT_ID=1100225360
DHAN_ACCESS_TOKEN=
SUPABASE_URL=
SUPABASE_KEY=
FAST2SMS_API_KEY=
EMAIL_SENDER=
EMAIL_PASSWORD=
EMAIL_RECEIVER=
EOF
  echo ""
  echo ">>> IMPORTANT: Edit /root/nse-trading-signals/.env and add your API keys"
  echo ">>> Run: nano /root/nse-trading-signals/.env"
fi

# Systemd service
echo ">>> Installing systemd service..."
cat > /etc/systemd/system/nse-trading.service << EOF
[Unit]
Description=NSE Trading Signals
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/nse-trading-signals
EnvironmentFile=/root/nse-trading-signals/.env
ExecStart=/root/nse-trading-signals/venv/bin/streamlit run app.py --server.port 8501 --server.address 0.0.0.0 --server.headless true
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable nse-trading
systemctl restart nse-trading

# Firewall
ufw allow 22/tcp
ufw allow 8501/tcp
ufw --force enable

echo ""
echo "========================================"
echo "  SETUP COMPLETE!"
echo "  App running at: http://168.144.158.30:8501"
echo ""
echo "  Check status:  systemctl status nse-trading"
echo "  View logs:     journalctl -u nse-trading -f"
echo "  Edit API keys: nano /root/nse-trading-signals/.env"
echo "========================================"
