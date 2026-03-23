"""Clerk JWT verification using JWKS (no shared secret needed).

Fetches Clerk's public keys from the JWKS endpoint and verifies
JWT signatures. Keys are cached with a 1-hour TTL.
"""

import os
import time
import jwt
import json
import urllib.request

_jwks_cache: dict | None = None
_jwks_cache_time: float = 0
_JWKS_CACHE_TTL = 3600  # 1 hour


def _get_clerk_issuer() -> str:
    """Derive the Clerk issuer URL from the publishable key."""
    pk = os.getenv("CLERK_PUBLISHABLE_KEY", "")
    if pk:
        import base64
        encoded = pk.split("_", 2)[-1].rstrip("$")
        encoded += "=" * (4 - len(encoded) % 4)
        domain = base64.b64decode(encoded).decode().rstrip("$")
        return f"https://{domain}"
    raise RuntimeError("CLERK_PUBLISHABLE_KEY is required")


def _get_jwks_url() -> str:
    """Derive JWKS URL from the Clerk publishable key or env var."""
    url = os.getenv("CLERK_JWKS_URL")
    if url:
        return url
    return f"{_get_clerk_issuer()}/.well-known/jwks.json"


def _fetch_jwks() -> dict:
    """Fetch and cache JWKS from Clerk with TTL."""
    global _jwks_cache, _jwks_cache_time
    now = time.monotonic()
    if _jwks_cache is not None and (now - _jwks_cache_time) < _JWKS_CACHE_TTL:
        return _jwks_cache
    url = _get_jwks_url()
    with urllib.request.urlopen(url, timeout=5) as resp:
        _jwks_cache = json.loads(resp.read())
    _jwks_cache_time = now
    return _jwks_cache


def verify_clerk_jwt(token: str) -> dict:
    """Verify a Clerk JWT and return the claims.

    Returns dict with at least: sub (user ID), plus any custom claims.
    Raises jwt.InvalidTokenError on failure.
    """
    jwks = _fetch_jwks()

    header = jwt.get_unverified_header(token)
    kid = header.get("kid")

    key_data = None
    for key in jwks.get("keys", []):
        if key.get("kid") == kid:
            key_data = key
            break

    if key_data is None:
        # Key not found — maybe keys rotated. Clear cache and retry once.
        global _jwks_cache, _jwks_cache_time
        _jwks_cache = None
        _jwks_cache_time = 0
        jwks = _fetch_jwks()
        for key in jwks.get("keys", []):
            if key.get("kid") == kid:
                key_data = key
                break

    if key_data is None:
        raise jwt.InvalidTokenError(f"No matching key found for kid={kid}")

    from jwt.algorithms import RSAAlgorithm
    public_key = RSAAlgorithm.from_jwk(key_data)

    # Verify issuer matches our Clerk instance
    expected_issuer = _get_clerk_issuer()

    claims = jwt.decode(
        token,
        public_key,
        algorithms=["RS256"],
        options={"verify_aud": False},
        issuer=expected_issuer,
    )
    return claims
