#!/bin/bash
# =================================================================
# V75 Dashboard — Oracle VPS First-Time Setup
# Run this ONCE on the server after cloning the repo.
# =================================================================

set -e

APP_DIR="/opt/v75-dashboard"
SERVICE_NAME="v75-dashboard"

echo "=== V75 Dashboard Server Setup ==="

# 1. System packages
echo "[1/7] Installing system packages..."
sudo apt-get update -qq
sudo apt-get install -y python3 python3-venv python3-pip nginx certbot python3-certbot-nginx

# 2. App directory
echo "[2/7] Setting up app directory..."
sudo mkdir -p $APP_DIR
sudo chown ubuntu:ubuntu $APP_DIR

# 3. Clone or copy files (assumes repo already cloned to $APP_DIR)
if [ ! -f "$APP_DIR/app.py" ]; then
    echo "ERROR: app.py not found in $APP_DIR"
    echo "Clone your repo first: git clone <your-repo-url> $APP_DIR"
    exit 1
fi

# 4. Python virtual environment
echo "[3/7] Creating Python venv..."
cd $APP_DIR
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# 5. Create D.env if missing
if [ ! -f "$APP_DIR/D.env" ]; then
    echo "[4/7] Creating D.env — YOU MUST EDIT THIS"
    cat > "$APP_DIR/D.env" << 'ENVEOF'
DERIV_API_TOKEN=YOUR_TOKEN_HERE
V75_PORT=8085
ENVEOF
    echo ">>> EDIT $APP_DIR/D.env with your Deriv API token!"
else
    echo "[4/7] D.env already exists, skipping"
fi

# 6. Systemd service
echo "[5/7] Installing systemd service..."
sudo cp $APP_DIR/deploy/v75-dashboard.service /etc/systemd/system/$SERVICE_NAME.service
sudo systemctl daemon-reload
sudo systemctl enable $SERVICE_NAME
sudo systemctl start $SERVICE_NAME
echo "Service status:"
sudo systemctl status $SERVICE_NAME --no-pager -l || true

# 7. Nginx
echo "[6/7] Configuring nginx..."
sudo cp $APP_DIR/deploy/nginx-v75.conf /etc/nginx/sites-available/v75-dashboard
sudo ln -sf /etc/nginx/sites-available/v75-dashboard /etc/nginx/sites-enabled/v75-dashboard
sudo nginx -t && sudo systemctl reload nginx

# 8. Firewall (Oracle Cloud uses iptables)
echo "[7/7] Opening ports 80 and 443..."
sudo iptables -I INPUT -p tcp --dport 80 -j ACCEPT 2>/dev/null || true
sudo iptables -I INPUT -p tcp --dport 443 -j ACCEPT 2>/dev/null || true

echo ""
echo "=== DONE ==="
echo "Dashboard should be live at: http://130.162.58.230"
echo ""
echo "To add HTTPS later (needs a domain name):"
echo "  sudo certbot --nginx -d yourdomain.com"
echo ""
echo "Useful commands:"
echo "  sudo systemctl status v75-dashboard"
echo "  sudo systemctl restart v75-dashboard"
echo "  sudo journalctl -u v75-dashboard -f"
