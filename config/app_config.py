"""
app_config.py
Flask and shared application configuration.
All values can be overridden with environment variables.
"""
import os

class Config:
    # ── Redis ────────────────────────────────────────────────────────────────
    REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    # ── Flask ────────────────────────────────────────────────────────────────
    SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "dev-secret-change-in-production")
    DEBUG = os.getenv("FLASK_DEBUG", "false").lower() == "true"

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

config_map = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
}
