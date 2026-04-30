"""
flower_config.py
Flower monitoring configuration.
Pass this file to Flower with: --conf=monitoring/flower_config.py
"""
import os

# ── Auth ─────────────────────────────────────────────────────────────────────
# Basic auth: "user:password"
basic_auth = [os.getenv("FLOWER_BASIC_AUTH", "admin:secret")]

# ── Server ───────────────────────────────────────────────────────────────────
port = int(os.getenv("FLOWER_PORT", 5555))
address = "0.0.0.0"

# ── Broker ───────────────────────────────────────────────────────────────────
broker_api = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# ── Task History ─────────────────────────────────────────────────────────────
# How many completed tasks to keep in Flower's in-memory history
max_tasks = 10000

# ── Refresh ──────────────────────────────────────────────────────────────────
# Auto-refresh interval for the dashboard (seconds)
auto_refresh = True

# ── Persistent State ─────────────────────────────────────────────────────────
# Store Flower state to a file so it survives restarts
db = "monitoring/flower.db"

# ── Logging ──────────────────────────────────────────────────────────────────
logging = "INFO"
