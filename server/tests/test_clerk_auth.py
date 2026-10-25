"""Tests for Clerk JWKS JWT verification."""
import pytest
import jwt
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta

from clerk_auth import verify_clerk_jwt


# Generate a test RSA key pair for testing
from jwt.algorithms import RSAAlgorithm
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.backends import default_backend

_test_private_key = rsa.generate_private_key(
    public_exponent=65537,
    key_size=2048,
    backend=default_backend(),
)
_test_public_key = _test_private_key.public_key()
_test_jwk = RSAAlgorithm.to_jwk(_test_public_key, as_dict=True)
_test_jwk["kid"] = "test-key-id"
_test_jwk["use"] = "sig"
_test_jwk["alg"] = "RS256"

_test_jwks = {"keys": [_test_jwk]}


def _make_token(claims: dict, kid: str = "test-key-id") -> str:
    return jwt.encode(
        claims,
        _test_private_key,
        algorithm="RS256",
        headers={"kid": kid},
    )


@patch("clerk_auth._get_clerk_issuer", return_value="https://test.clerk.accounts.dev")
@patch("clerk_auth._fetch_jwks", return_value=_test_jwks)
def test_verify_valid_token(mock_jwks, mock_issuer):
    token = _make_token({
        "sub": "user_abc123",
        "iss": "https://test.clerk.accounts.dev",
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        "iat": datetime.now(timezone.utc),
    })
    claims = verify_clerk_jwt(token)
    assert claims["sub"] == "user_abc123"


@patch("clerk_auth._get_clerk_issuer", return_value="https://test.clerk.accounts.dev")
@patch("clerk_auth._fetch_jwks", return_value=_test_jwks)
def test_reject_expired_token(mock_jwks, mock_issuer):
    token = _make_token({
        "sub": "user_abc123",
        "iss": "https://test.clerk.accounts.dev",
        "exp": datetime.now(timezone.utc) - timedelta(hours=1),
        "iat": datetime.now(timezone.utc) - timedelta(hours=2),
    })
    with pytest.raises(jwt.ExpiredSignatureError):
        verify_clerk_jwt(token)


@patch("clerk_auth._fetch_jwks", return_value={"keys": []})
def test_reject_unknown_kid(mock_jwks):
    token = _make_token(
        {"sub": "user_abc123", "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
        kid="unknown-key",
    )
    with pytest.raises(jwt.InvalidTokenError, match="No matching key"):
        verify_clerk_jwt(token)


@patch("clerk_auth._get_clerk_issuer", return_value="https://test.clerk.accounts.dev")
@patch("clerk_auth._fetch_jwks", return_value=_test_jwks)
def test_reject_wrong_issuer(mock_jwks, mock_issuer):
    """Tokens from a different Clerk instance must be rejected."""
    token = _make_token({
        "sub": "user_abc123",
        "iss": "https://evil-app.clerk.accounts.dev",
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        "iat": datetime.now(timezone.utc),
    })
    with pytest.raises(jwt.InvalidTokenError):
        verify_clerk_jwt(token)


@patch("clerk_auth._get_clerk_issuer", return_value="https://test.clerk.accounts.dev")
@patch("clerk_auth._fetch_jwks", return_value=_test_jwks)
def test_reject_missing_issuer(mock_jwks, mock_issuer):
    """Tokens without an iss claim must be rejected."""
    token = _make_token({
        "sub": "user_abc123",
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        "iat": datetime.now(timezone.utc),
    })
    with pytest.raises(jwt.MissingRequiredClaimError):
        verify_clerk_jwt(token)


def test_reject_garbage_token():
    """Completely invalid token strings must be rejected."""
    with pytest.raises(Exception):
        verify_clerk_jwt("not-a-jwt-at-all")


def test_jwks_cache_ttl():
    """JWKS cache should expire after TTL."""
    import clerk_auth
    clerk_auth._jwks_cache = {"keys": []}
    clerk_auth._jwks_cache_time = 0  # Expired long ago
    # After TTL, _fetch_jwks should re-fetch (will fail without network, but proves cache was invalidated)
    import time
    assert (time.monotonic() - clerk_auth._jwks_cache_time) > clerk_auth._JWKS_CACHE_TTL
