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
 
