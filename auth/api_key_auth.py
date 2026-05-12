"""
API key authentication middleware for the Flask API.
 
Design decisions:
  - Keys are stored hashed (SHA-256) in config — never in plaintext.
  - Each key has a name, role, and optional rate limit and expiry.
  - Two roles:  "admin"   → full access (submit, revoke, inspect workers)
               "readonly" → GET endpoints only (status, workers, queues)
  - /health is public — no key required (used by load-balancers/uptime monitors).
  - The key is passed in the X-API-Key header (industry standard).
  - Rate limiting is per-key using a Redis sliding window counter.
  - All auth decisions are logged with the key name (never the raw key).
 
Usage in api.py:
    from app.auth.api_key_auth import require_api_key, require_admin
 
    @app.route("/tasks/...", methods=["POST"])
    @require_api_key          # any valid key
    def submit_task(): ...
 
    @app.route("/workers", methods=["GET"])
    @require_admin            # admin role only
    def list_workers(): ...
 
Generating a key:
    python scripts/generate_api_key.py --name "ci-pipeline" --role admin
"""

import hashlib
import logging
import time
from datetime import datetime, timezone
from functools import wraps
from typing import Optional
 
import redis as redis_lib
from flask import request, jsonify, g
 
from config.app_config import Config
 
logger = logging.getLogger(__name__)
 
# ── Key registry ──────────────────────────────────────────────────────────────
# Maps SHA-256(raw_key) → key metadata.
# Populate this from environment variables or a secrets manager in production.
# Generate hashes with: python scripts/generate_api_key.py
#
# Schema per entry:
#   name          human-readable label for logging/auditing
#   role          "admin" | "readonly"
#   rate_limit    max requests per minute (None = unlimited)
#   expires_at    ISO-8601 UTC string or None
#   enabled       set to False to instantly revoke without deleting the key
#
_KEY_REGISTRY: dict[str, dict] = {}

def _load_keys_from_config() -> dict[str, dict]:
    """
    Build the key registry from Config.API_KEYS.
    Config.API_KEYS is a list of dicts loaded from the API_KEYS env var (JSON).
    This function is called once at startup.
    """
    registry = {}
    for entry in Config.API_KEYS:
        raw_key = entry.get("key", "")
        if not raw_key:
            logger.warning("[auth] Skipping key entry with no 'key' field")
            continue
        key_hash = _hash_key(raw_key)
        registry[key_hash] = {
            "name": entry.get("name", "unnamed"),
            "role": entry.get("role", "readonly"),
            "rate_limit": entry.get("rate_limit", None),   # req/min, None = unlimited
            "expires_at": entry.get("expires_at", None),   # ISO string or None
            "enabled": entry.get("enabled", True),
        }
    logger.info(f"[auth] Loaded {len(registry)} API key(s)")
    return registry
 
 
def _hash_key(raw_key: str) -> str:
    """SHA-256 hash of the raw API key. Keys are never stored in plaintext."""
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
 
 
def _get_registry() -> dict[str, dict]:
    """Return the live registry, loading it on first call."""
    global _KEY_REGISTRY
    if not _KEY_REGISTRY:
        _KEY_REGISTRY = _load_keys_from_config()
    return _KEY_REGISTRY
 
 
def reload_keys():
    """Force-reload the key registry (call after a config change)."""
    global _KEY_REGISTRY
    _KEY_REGISTRY = _load_keys_from_config()
    logger.info("[auth] Key registry reloaded")
 
