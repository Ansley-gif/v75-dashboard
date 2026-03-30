#!/bin/bash
# =================================================================
# V75 Dashboard — Quick Update (run on server after git pull)
# =================================================================

set -e

cd /opt/v75-dashboard
git pull
source venv/bin/activate
pip install -r requirements.txt --quiet
sudo systemctl restart v75-dashboard

echo "V75 Dashboard updated and restarted."
echo "Check status: sudo systemctl status v75-dashboard"
echo "Check logs:   sudo journalctl -u v75-dashboard -f"
