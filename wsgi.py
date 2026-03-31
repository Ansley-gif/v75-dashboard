"""
WSGI entry point for V75 Dashboard (gunicorn).
Starts all background services before serving.
"""
import os
from dotenv import load_dotenv
load_dotenv("D.env")

from app import app, init_db, data_service, regime_update_loop, alert_loop, agent_memory_loop
import threading

# Initialize database
init_db()

# Start Deriv WebSocket data feed
data_service.start()

# Start background threads
threading.Thread(target=regime_update_loop, daemon=True).start()
threading.Thread(target=alert_loop, daemon=True).start()
threading.Thread(target=agent_memory_loop, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("V75_PORT", 8085))
    app.run(host="0.0.0.0", port=port, debug=False)
