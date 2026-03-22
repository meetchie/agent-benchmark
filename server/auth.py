"""Authentication helpers — password hashing, JWT encode/decode, signup/signin."""

import os
import re
from datetime import datetime, timezone, timedelta

import bcrypt
import jwt

from database import create_user, get_user_by_email


_SECRET = None


def _get_secret() -> str:
    global _SECRET
    if _SECRET is None:
        _SECRET = os.getenv("AUTH_SECRET")
        if not _SECRET:
            raise RuntimeError("AUTH_SECRET not set")
    return _SECRET


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), password_hash.encode())


def encode_jwt(user_id: str, email: str) -> str:
    payload = {
        "user_id": str(user_id),
        "email": email,
        "exp": datetime.now(timezone.utc) + timedelta(days=7),
    }
    return jwt.encode(payload, _get_secret(), algorithm="HS256")


def decode_jwt(token: str) -> dict:
    """Decode and verify a JWT. Raises jwt.InvalidTokenError on failure."""
    return jwt.decode(token, _get_secret(), algorithms=["HS256"])


def validate_email(email: str) -> bool:
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email))


async def signup(email: str, password: str) -> dict:
    """Create a new user account. Returns {token}."""
    email = email.strip().lower()
    if not validate_email(email):
        raise ValueError("Invalid email format")
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters")

    pw_hash = hash_password(password)
    user = await create_user(email, pw_hash)
    token = encode_jwt(user["id"], email)
    return {"token": token}


async def signin(email: str, password: str) -> dict:
    """Sign in with email and password. Returns {token}."""
    email = email.strip().lower()
    user = await get_user_by_email(email)
    if not user or not verify_password(password, user["password_hash"]):
        raise PermissionError("Invalid email or password")

    token = encode_jwt(user["id"], user["email"])
    return {"token": token}
