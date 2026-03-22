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


@patch("clerk_auth._fetch_jwks", return_value=_test_jwks)
def test_verify_valid_token(mock_jwks):
    token = _make_token({
        "sub": "user_abc123",
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        "iat": datetime.now(timezone.utc),
    })
    claims = verify_clerk_jwt(token)
    assert claims["sub"] == "user_abc123"


@patch("clerk_auth._fetch_jwks", return_value=_test_jwks)
def test_reject_expired_token(mock_jwks):
    token = _make_token({
        "sub": "user_abc123",
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
