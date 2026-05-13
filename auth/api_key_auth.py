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

# ── Rate limiting (Redis sliding window) ─────────────────────────────────────
 
def _check_rate_limit(key_name: str, rate_limit: Optional[int]) -> tuple[bool, dict]:
    """
    Sliding-window rate limiter using Redis INCR + EXPIRE.
 
    Args:
        key_name:   Human-readable key name (used as Redis key suffix).
        rate_limit: Max allowed requests per 60-second window. None = skip.
 
    Returns:
        (allowed: bool, headers: dict)  — headers go into the HTTP response.
    """
    if rate_limit is None:
        return True, {}
 
    try:
        r = redis_lib.from_url(Config.REDIS_URL, socket_connect_timeout=1)
        window = int(time.time()) // 60          # 1-minute bucket
        redis_key = f"ratelimit:{key_name}:{window}"
 
        current = r.incr(redis_key)
        if current == 1:
            r.expire(redis_key, 120)             # 2-minute TTL (covers current + previous window)
 
        remaining = max(0, rate_limit - current)
        reset_at = (window + 1) * 60            # epoch seconds when window resets
 
        headers = {
            "X-RateLimit-Limit": str(rate_limit),
            "X-RateLimit-Remaining": str(remaining),
            "X-RateLimit-Reset": str(reset_at),
        }
 
        if current > rate_limit:
            logger.warning(f"[auth] Rate limit exceeded for key '{key_name}' ({current}/{rate_limit})")
            return False, headers
 
        return True, headers
 
    except Exception as exc:
        # If Redis is unreachable, fail open (don't block legitimate traffic)
        logger.error(f"[auth] Rate limit check failed (failing open): {exc}")
        return True, {}
 
 
# ── Core validation ───────────────────────────────────────────────────────────
 
def _validate_request() -> tuple[Optional[dict], Optional[tuple]]:
    """
    Validate the incoming request's API key.
 
    Returns:
        (key_meta, None)        on success — key_meta is the registry entry
        (None, error_response)  on failure — error_response is a Flask response tuple
    """
    raw_key = request.headers.get("X-API-Key", "").strip()
 
    if not raw_key:
        logger.warning(f"[auth] Missing X-API-Key header — {request.method} {request.path}")
        return None, (
            jsonify({"error": "Missing API key", "hint": "Set the X-API-Key header"}),
            401,
        )
 
    key_hash = _hash_key(raw_key)
    registry = _get_registry()
    key_meta = registry.get(key_hash)
 
    if key_meta is None:
        logger.warning(f"[auth] Invalid API key — {request.method} {request.path} from {_client_ip()}")
        return None, (jsonify({"error": "Invalid API key"}), 403)
 
    if not key_meta.get("enabled", True):
        logger.warning(f"[auth] Disabled key '{key_meta['name']}' used — {request.path}")
        return None, (jsonify({"error": "API key has been revoked"}), 403)
 
    # Check expiry
    expires_at = key_meta.get("expires_at")
    if expires_at:
        try:
            expiry = datetime.fromisoformat(expires_at)
            if datetime.now(timezone.utc) > expiry:
                logger.warning(f"[auth] Expired key '{key_meta['name']}' used")
                return None, (jsonify({"error": "API key has expired"}), 403)
        except ValueError:
            logger.error(f"[auth] Invalid expires_at format for key '{key_meta['name']}'")
 
    return key_meta, None

# ── Decorators ────────────────────────────────────────────────────────────────
 
def require_api_key(f):
    """
    Decorator: any valid, enabled, non-expired API key passes.
    Applies rate limiting if the key has a rate_limit set.
    Stores key metadata in Flask's g object for use in the view.
 
    Example:
        @app.route("/tasks/sample/add", methods=["POST"])
        @require_api_key
        def submit_add(): ...
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        key_meta, error = _validate_request()
        if error:
            return error
 
        # Rate limiting
        allowed, rl_headers = _check_rate_limit(key_meta["name"], key_meta.get("rate_limit"))
        if not allowed:
            resp = jsonify({
                "error": "Rate limit exceeded",
                "retry_after": rl_headers.get("X-RateLimit-Reset"),
            })
            resp.status_code = 429
            for k, v in rl_headers.items():
                resp.headers[k] = v
            return resp
 
        # Expose key info to the view via Flask's g
        g.api_key_name = key_meta["name"]
        g.api_key_role = key_meta["role"]
 
        logger.info(
            f"[auth] Authorized key='{key_meta['name']}' role={key_meta['role']} "
            f"— {request.method} {request.path}"
        )
 
        response = f(*args, **kwargs)
 
        # Attach rate-limit headers to the response
        if rl_headers:
            if hasattr(response, "headers"):
                for k, v in rl_headers.items():
                    response.headers[k] = v
 
        return response
 
    return decorated 

def require_admin(f):
    """
    Decorator: only admin-role keys pass. Implies require_api_key.
 
    Example:
        @app.route("/workers", methods=["GET"])
        @require_admin
        def list_workers(): ...
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        key_meta, error = _validate_request()
        if error:
            return error
         
        if key_meta.get("role") != "admin":
            logger.warning(
                f"[auth] Forbidden — key='{key_meta['name']}' role={key_meta['role']} "
                f"tried admin endpoint {request.path}"
            )
            return jsonify({
                "error": "Forbidden",
                "detail": "This endpoint requires an admin API key",
            }), 403
 
        allowed, rl_headers = _check_rate_limit(key_meta["name"], key_meta.get("rate_limit"))
        if not allowed:
            resp = jsonify({"error": "Rate limit exceeded"})
            resp.status_code = 429
            for k, v in rl_headers.items():
                resp.headers[k] = v
            return resp
 
        g.api_key_name = key_meta["name"]
        g.api_key_role = key_meta["role"]
 
        logger.info(
            f"[auth] Admin authorized key='{key_meta['name']}' "
            f"— {request.method} {request.path}"
        )
        return f(*args, **kwargs)
 
    return decorated 

# ── Helpers ───────────────────────────────────────────────────────────────────
 
def _client_ip() -> str:
    """Best-effort client IP, respecting X-Forwarded-For from reverse proxies."""
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "unknown"
