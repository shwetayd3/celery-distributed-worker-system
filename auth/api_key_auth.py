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
