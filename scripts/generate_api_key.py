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
