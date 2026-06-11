"""
Flask and shared application configuration.
All values can be overridden with environment variables.
 
API key format (set as JSON in the API_KEYS env var):
    export API_KEYS='[
      {"key": "secret-admin-key",    "name": "local-dev",  "role": "admin",    "rate_limit": 120},
      {"key": "secret-readonly-key", "name": "ci-monitor", "role": "readonly", "rate_limit": 60}
    ]'
 
Generate hashed keys safely with:
    python scripts/generate_api_key.py --name "my-service" --role admin
"""

import os
import json
import logging
 
logger = logging.getLogger(__name__)

def _load_api_keys() -> list:
    """
    Load API keys from the API_KEYS environment variable (JSON array).
    Falls back to a single dev key when running locally without any env var set.
    The dev key is logged at WARNING so it is never silently active in production.
    """
    raw = os.getenv("API_KEYS", "")
    if raw:
        try:
            keys = json.loads(raw)
            if not isinstance(keys, list):
                raise ValueError("API_KEYS must be a JSON array")
            logger.info(f"[config] Loaded {len(keys)} API key(s) from environment")
            return keys
        except (json.JSONDecodeError, ValueError) as exc:
            logger.error(f"[config] Failed to parse API_KEYS env var: {exc}. No keys loaded.")
            return []
 
    # Dev fallback — NEVER rely on this in staging or production.
    dev_key = "dev-only-insecure-key-change-me"
    logger.warning(
        "[config] API_KEYS env var not set — using insecure dev key. "
        "Set API_KEYS in production!"
    )
    return [
        {
            "key": dev_key,
            "name": "dev-fallback",
            "role": "admin",
            "rate_limit": None,
            "enabled": True,
        }
    ]

class Config:
    # ── Redis ────────────────────────────────────────────────────────────────
    REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    # ── Flask ────────────────────────────────────────────────────────────────
    SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "dev-secret-change-in-production")
    DEBUG = os.getenv("FLASK_DEBUG", "false").lower() == "true"

    # API Key Auth
    API_KEYS = _load_api_keys()

    # ── Result cleanup ───────────────────────────────────────────────────────
    RESULT_TTL_SECONDS = int(os.getenv("RESULT_TTL_SECONDS", 3600))

    # Dead-Letter Queue
    DLQ_TTL_DAYS = int(os.getenv("DLQ_TTL_DAYS", 30))   # entries older than this are pruned

    # ── Flower ───────────────────────────────────────────────────────────────
    FLOWER_PORT = int(os.getenv("FLOWER_PORT", 5555))
    FLOWER_BASIC_AUTH = os.getenv("FLOWER_BASIC_AUTH", "admin:secret")

    # ── Worker ───────────────────────────────────────────────────────────────
    WORKER_CONCURRENCY = int(os.getenv("WORKER_CONCURRENCY", 4))


class DevelopmentConfig(Config):
    DEBUG = True


class ProductionConfig(Config):
    DEBUG = False


class TestingConfig(Config):
    TESTING = True
    REDIS_URL = "memory://"   # In-memory broker for unit tests
    DLQ_TTL_DAYS = 30
 
    API_KEYS = [
        {"key": "test-admin-key",    "name": "test-admin",    "role": "admin",    "rate_limit": None, "enabled": True},
        {"key": "test-readonly-key", "name": "test-readonly", "role": "readonly", "rate_limit": None, "enabled": True},
        {"key": "test-expired-key",  "name": "test-expired",  "role": "admin",    "rate_limit": None, "enabled": True,
         "expires_at": "2000-01-01T00:00:00+00:00"},
        {"key": "test-disabled-key", "name": "test-disabled", "role": "admin",    "rate_limit": None, "enabled": False},
        {"key": "test-limited-key",  "name": "test-limited",  "role": "admin",    "rate_limit": 2,    "enabled": True},
    ]


config_map = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
}
