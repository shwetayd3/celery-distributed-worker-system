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
