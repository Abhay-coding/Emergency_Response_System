from datetime import datetime, timedelta, timezone
from uuid import uuid4

import jwt
from pwdlib import PasswordHash

from app.core.config import settings

password_hash = PasswordHash.recommended()
ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return password_hash.verify(password, hashed)


def create_access_token(subject: str) -> str:
    expiry = datetime.now(timezone.utc) + timedelta(
        minutes=settings.access_token_minutes
    )
    return jwt.encode(
        {"sub": subject, "exp": expiry, "type": "access", "jti": str(uuid4())},
        settings.jwt_secret,
        algorithm=ALGORITHM,
    )


def create_refresh_token(subject: str, family_id: str | None = None) -> str:
    """Create a refresh token with optional family ID for theft detection"""
    expiry = datetime.now(timezone.utc) + timedelta(
        days=settings.refresh_token_days
    )
    payload = {
        "sub": subject,
        "exp": expiry,
        "type": "refresh",
        "jti": str(uuid4()),
    }
    if family_id:
        payload["fid"] = family_id
    return jwt.encode(
        payload,
        settings.jwt_secret,
        algorithm=ALGORITHM,
    )


def decode_access_token(token: str) -> dict:
    payload = jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[ALGORITHM],
    )
    if payload.get("type") != "access":
        raise jwt.InvalidTokenError("Invalid token type")
    return payload


def decode_refresh_token(token: str) -> dict:
    payload = jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[ALGORITHM],
    )
    if payload.get("type") != "refresh":
        raise jwt.InvalidTokenError("Invalid token type")
    return payload


def get_token_jti(token: str) -> str | None:
    """Extract JTI from token without full validation (for blacklist check)"""
    try:
        # Decode without verification to get JTI
        payload = jwt.decode(
            token,
            options={"verify_signature": False, "verify_exp": False},
            algorithms=[ALGORITHM],
        )
        return payload.get("jti")
    except jwt.InvalidTokenError:
        return None


def get_refresh_token_family(token: str) -> str | None:
    """Extract family ID from refresh token"""
    try:
        payload = jwt.decode(
            token,
            options={"verify_signature": False, "verify_exp": False},
            algorithms=[ALGORITHM],
        )
        return payload.get("fid")
    except jwt.InvalidTokenError:
        return None
