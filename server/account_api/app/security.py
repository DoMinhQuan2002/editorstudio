import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from .config import get_settings

JWT_ALG = "HS256"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        return False
    return bcrypt.checkpw(password.encode(), password_hash.encode())


def new_otp_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_secret(value: str) -> str:
    """Keyed hash for OTP codes and refresh tokens (never stored in plain text)."""
    key = get_settings().jwt_secret.encode()
    return hmac.new(key, value.encode(), hashlib.sha256).hexdigest()


def same_secret(value: str, stored_hash: str) -> bool:
    return hmac.compare_digest(hash_secret(value), stored_hash)


def new_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def create_access_token(user_id: uuid.UUID, device_id: uuid.UUID) -> tuple[str, int]:
    settings = get_settings()
    lifetime = settings.access_token_minutes * 60
    now = datetime.now(timezone.utc)
    payload = {"sub": str(user_id), "did": str(device_id), "iat": now,
               "exp": now + timedelta(seconds=lifetime), "typ": "access"}
    return jwt.encode(payload, settings.jwt_secret, algorithm=JWT_ALG), lifetime


def decode_access_token(token: str) -> dict:
    payload = jwt.decode(token, get_settings().jwt_secret, algorithms=[JWT_ALG])
    if payload.get("typ") != "access":
        raise jwt.InvalidTokenError("wrong token type")
    return payload
