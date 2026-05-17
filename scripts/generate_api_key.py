#!/usr/bin/env python3
""" 
Generate a secure API key and print the JSON entry to add to API_KEYS.
 
Usage:
    python scripts/generate_api_key.py --name "ci-pipeline" --role admin
    python scripts/generate_api_key.py --name "monitor" --role readonly --rate-limit 60
    python scripts/generate_api_key.py --name "temp" --role admin --expires-days 30
 
Output:
    Raw key   → copy this into your .env / secrets manager as the bearer value
    JSON entry → copy this into your API_KEYS JSON array
 
Never store the raw key in source control.
"""

import argparse
import hashlib
import json
import secrets
import string
from datetime import datetime, timezone, timedelta
 
def generate_key(length: int = 40) -> str:
    """Generate a cryptographically secure random key."""
    alphabet = string.ascii_letters + string.digits + "-_"
    return "".join(secrets.choice(alphabet) for _ in range(length))
 
def hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()
 
def main():
    parser = argparse.ArgumentParser(description="Generate a Celery API key")
    parser.add_argument("--name",        required=True,  help="Human-readable label (e.g. 'ci-pipeline')")
    parser.add_argument("--role",        required=True,  choices=["admin", "readonly"], help="Key role")
    parser.add_argument("--rate-limit",  type=int,       default=None, help="Max requests per minute (omit for unlimited)")
    parser.add_argument("--expires-days",type=int,       default=None, help="Key validity in days (omit for no expiry)")
    parser.add_argument("--disabled",    action="store_true",          help="Create the key in disabled state")
    parser.add_argument("--length",      type=int,       default=40,   help="Key length in characters (default: 40)")
    args = parser.parse_args()
 
    raw_key = generate_key(args.length)
    key_hash = hash_key(raw_key)
 
    expires_at = None
    if args.expires_days:
        expires_at = (
            datetime.now(timezone.utc) + timedelta(days=args.expires_days)
        ).isoformat()
 
    entry = {
        "key": raw_key,         # This field is used at load time; swap for key_hash in DB-backed setups
        "name": args.name,
        "role": args.role,
        "rate_limit": args.rate_limit,
        "expires_at": expires_at,
        "enabled": not args.disabled,
    }
 
    sep = "─" * 60
    print(f"\n{sep}")
    print(f"  API Key Generated")
    print(sep)
    print(f"  Name       : {args.name}")
    print(f"  Role       : {args.role}")
    print(f"  Rate limit : {args.rate_limit or 'unlimited'} req/min")
    print(f"  Expires    : {expires_at or 'never'}")
    print(f"  Enabled    : {not args.disabled}")
    print(sep)
    print(f"\n  RAW KEY (set this as X-API-Key in requests):\n")
    print(f"    {raw_key}")
    print(f"\n  SHA-256 HASH (for reference):\n")
    print(f"    {key_hash}")
    print(f"\n  JSON ENTRY (add this to your API_KEYS env var):\n")
    print(f"    {json.dumps(entry, indent=4)}")
    print(f"\n{sep}")
    print(" Store the raw key securely. It cannot be recovered.")
    print(f"{sep}\n")
if __name__ == "__main__":
    main()
