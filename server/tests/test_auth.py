import pytest
import os
from unittest.mock import patch, AsyncMock

os.environ.setdefault("AUTH_SECRET", "test-secret-key-for-testing")

from auth import hash_password, verify_password, encode_jwt, decode_jwt, validate_email


def test_password_hash_and_verify():
    pw = "mypassword123"
    hashed = hash_password(pw)
    assert hashed != pw
    assert verify_password(pw, hashed)
    assert not verify_password("wrongpassword", hashed)


def test_jwt_encode_decode():
    token = encode_jwt("user-123", "test@example.com")
    payload = decode_jwt(token)
    assert payload["user_id"] == "user-123"
    assert payload["email"] == "test@example.com"


def test_validate_email():
    assert validate_email("user@example.com")
    assert validate_email("user.name@domain.co")
    assert not validate_email("not-an-email")
    assert not validate_email("@domain.com")
    assert not validate_email("")


@pytest.mark.asyncio
async def test_signup_validates_email():
    from auth import signup
    with pytest.raises(ValueError, match="Invalid email"):
        await signup("not-an-email", "password123")


@pytest.mark.asyncio
async def test_signup_validates_password_length():
    from auth import signup
    with pytest.raises(ValueError, match="at least 8"):
        await signup("user@example.com", "short")


@pytest.mark.asyncio
async def test_signup_success():
    from auth import signup
    mock_user = {"id": "uuid-123", "email": "test@example.com", "created_at": "now"}
    with patch("auth.create_user", new_callable=AsyncMock, return_value=mock_user):
        result = await signup("test@example.com", "password123")
    assert "token" in result
    payload = decode_jwt(result["token"])
    assert payload["email"] == "test@example.com"


@pytest.mark.asyncio
async def test_signin_bad_credentials():
    from auth import signin
    with patch("auth.get_user_by_email", new_callable=AsyncMock, return_value=None):
        with pytest.raises(PermissionError, match="Invalid email"):
            await signin("noone@example.com", "password123")
