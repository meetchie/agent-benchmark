"""Clerk JWT verification using JWKS (no shared secret needed).

Fetches Clerk's public keys from the JWKS endpoint and verifies
JWT signatures. Keys are cached in memory for the process lifetime.

Note: JWKS cache never expires (cleared only on unknown kid). If Clerk
rotates keys, a process restart may be needed in the unlikely case that
the kid stays the same but key material changes. Acceptable for MVP.
"""

import os
import jwt
import json
import urllib.request

_jwks_cache: dict | None = None


def _get_jwks_url() -> str:
    """Derive JWKS URL from the Clerk publishable key or env var."""
    url = os.getenv("CLERK_JWKS_URL")
    if url:
        return url
    pk = os.getenv("CLERK_PUBLISHABLE_KEY", "")
    if pk:
        import base64
        encoded = pk.split("_", 2)[-1].rstrip("$")
        encoded += "=" * (4 - len(encoded) % 4)
        domain = base64.b64decode(encoded).decode()
        return f"https://{domain}/.well-known/jwks.json"
    raise RuntimeError("CLERK_PUBLISHABLE_KEY or CLERK_JWKS_URL is required")


def _fetch_jwks() -> dict:
    """Fetch and cache JWKS from Clerk."""
    global _jwks_cache
    if _jwks_cache is not None:
        return _jwks_cache
    url = _get_jwks_url()
    with urllib.request.urlopen(url, timeout=5) as resp:
        _jwks_cache = json.loads(resp.read())
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
        global _jwks_cache
        _jwks_cache = None
        jwks = _fetch_jwks()
        for key in jwks.get("keys", []):
            if key.get("kid") == kid:
                key_data = key
                break

    if key_data is None:
        raise jwt.InvalidTokenError(f"No matching key found for kid={kid}")

    from jwt.algorithms import RSAAlgorithm
    public_key = RSAAlgorithm.from_jwk(key_data)

    claims = jwt.decode(
        token,
        public_key,
        algorithms=["RS256"],
        options={"verify_aud": False},
    )
    return claims
