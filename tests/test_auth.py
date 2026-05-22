"""
Tests for API key authentication middleware.
 
Covers:
  - Missing key → 401
  - Invalid key → 403
  - Disabled key → 403
  - Expired key → 403
  - Valid readonly key on readonly endpoint → 200/202
  - Valid readonly key on admin endpoint → 403
  - Valid admin key on admin endpoint → 200/202
  - Public /health endpoint → 200 with no key
  - /auth/whoami returns correct name and role
  - Rate limiting → 429 after limit exceeded
  - Rate limit headers present on responses
  - Key registry reload via /auth/reload
 
Run with: pytest tests/test_auth.py -v
"""

import pytest
import json
from unittest.mock import patch, MagicMock
 
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
 
# Inject test config BEFORE importing the app so Config.API_KEYS is the test set
os.environ["API_KEYS"] = json.dumps([
    {"key": "test-admin-key",    "name": "test-admin",    "role": "admin",    "rate_limit": None, "enabled": True},
    {"key": "test-readonly-key", "name": "test-readonly", "role": "readonly", "rate_limit": None, "enabled": True},
    {"key": "test-expired-key",  "name": "test-expired",  "role": "admin",    "rate_limit": None, "enabled": True,
     "expires_at": "2000-01-01T00:00:00+00:00"},
    {"key": "test-disabled-key", "name": "test-disabled", "role": "admin",    "rate_limit": None, "enabled": False},
    {"key": "test-limited-key",  "name": "test-limited",  "role": "admin",    "rate_limit": 2,    "enabled": True},
])
 
from app.api import app
import app.auth.api_key_auth as auth_module
 
 
# ── Fixtures ──────────────────────────────────────────────────────────────────
 
@pytest.fixture(autouse=True)
def reset_key_registry():
    """Force-reload the key registry before each test."""
    auth_module._KEY_REGISTRY = {}
    auth_module.reload_keys()
    yield
    auth_module._KEY_REGISTRY = {}
 
 
@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c

def auth_header(key: str) -> dict:
    return {"X-API-Key": key}
 
def make_mock_task(task_id="t1", status="PENDING"):
    m = MagicMock()
    m.id = task_id
    m.status = status
    m.successful.return_value = False
    m.failed.return_value = False
    return m


# ── Public endpoints ──────────────────────────────────────────────────────────
 
class TestPublicEndpoints:
    def test_health_no_key(self, client):
        """GET /health must be accessible without any API key."""
        res = client.get("/health")
        assert res.status_code == 200
        assert res.get_json()["status"] == "ok"
 
    def test_health_with_invalid_key_still_works(self, client):
        """Even an invalid key should not affect the public /health endpoint."""
        res = client.get("/health", headers={"X-API-Key": "garbage"})
        assert res.status_code == 200


# ── Missing / invalid key ─────────────────────────────────────────────────────
 
class TestMissingAndInvalidKey:
    def test_missing_key_returns_401(self, client):
        res = client.post("/tasks/sample/add", json={"x": 1, "y": 2})
        assert res.status_code == 401
        data = res.get_json()
        assert "Missing API key" in data["error"]
        assert "hint" in data
 
    def test_empty_key_returns_401(self, client):
        res = client.post("/tasks/sample/add", json={"x": 1, "y": 2},
                          headers={"X-API-Key": ""})
        assert res.status_code == 401
 
    def test_wrong_key_returns_403(self, client):
        res = client.post("/tasks/sample/add", json={"x": 1, "y": 2},
                          headers=auth_header("completely-wrong-key"))
        assert res.status_code == 403
        assert "Invalid API key" in res.get_json()["error"]
 
    def test_almost_correct_key_returns_403(self, client):
        """One character different from a valid key must be rejected."""
        res = client.post("/tasks/sample/add", json={"x": 1, "y": 2},
                          headers=auth_header("test-admin-ke"))  # truncated
        assert res.status_code == 403
     
# ── Disabled and expired keys ─────────────────────────────────────────────────
 
class TestRevokedAndExpiredKeys:
    def test_disabled_key_returns_403(self, client):
        res = client.post("/tasks/sample/add", json={"x": 1, "y": 2},
                          headers=auth_header("test-disabled-key"))
        assert res.status_code == 403
        assert "revoked" in res.get_json()["error"].lower()
 
    def test_expired_key_returns_403(self, client):
        res = client.post("/tasks/sample/add", json={"x": 1, "y": 2},
                          headers=auth_header("test-expired-key"))
        assert res.status_code == 403
        assert "expired" in res.get_json()["error"].lower()

# ── Role-based access control ─────────────────────────────────────────────────
 
class TestRBAC:
    @patch("app.api.add")
    def test_admin_key_can_submit_tasks(self, mock_task, client):
        mock_task.apply_async.return_value = make_mock_task()
        res = client.post("/tasks/sample/add", json={"x": 1, "y": 2},
                          headers=auth_header("test-admin-key"))
        assert res.status_code == 202
