from datetime import datetime, timedelta, timezone
from uuid import uuid4

import jwt
from pwdlib import PasswordHash
from fastapi import Response

from app.core.config import settings
from app.models import CURRENT_PASSWORD_HASH_VERSION

password_hash = PasswordHash.recommended()
ALGORITHM = "HS256"

# Cookie path constant
COOKIE_PATH = "/"


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return password_hash.verify(password, hashed)


def needs_rehash(hashed: str) -> bool:
    """Check if the password hash needs to be upgraded to current parameters"""
    try:
        return password_hash.needs_rehash(hashed)
    except Exception:
        # If we can't determine, assume it needs rehashing
        return True


def is_password_hash_outdated(version: int | None) -> bool:
    """Check if a password hash version is outdated"""
    if version is None:
        return True
    return version < CURRENT_PASSWORD_HASH_VERSION


def upgrade_password_hash(password: str, hashed: str, version: int | None = None) -> str | None:
    """Upgrade password hash if needed. Returns new hash or None if not needed/failed.

    Args:
        password: Plaintext password (required for rehashing)
        hashed: Current password hash
        version: Current password hash version

    Returns:
        New hash if upgrade needed, None otherwise
    """
    # Check if hash version is outdated
    if is_password_hash_outdated(version):
        try:
            return hash_password(password)
        except Exception:
            return None

    # Also check if hash parameters need updating (e.g., Argon2 parameters changed)
    if needs_rehash(hashed):
        try:
            return hash_password(password)
        except Exception:
            return None

    return None


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


def set_auth_cookies(response: Response, access_token: str, refresh_token: str) -> None:
    """Set JWT tokens as secure HTTP-only cookies.

    Args:
        response: FastAPI Response object
        access_token: JWT access token
        refresh_token: JWT refresh token
    """
    # Calculate cookie expiry from token settings
    access_expiry = settings.access_token_minutes * 60  # seconds
    refresh_expiry = settings.refresh_token_days * 24 * 60 * 60  # seconds

    # Cookie security settings from config (environment-aware)
    cookie_secure = settings.cookie_secure
    cookie_httponly = settings.cookie_httponly
    cookie_samesite = settings.cookie_samesite

    # Set access token cookie
    response.set_cookie(
        key="access_token",
        value=access_token,
        max_age=access_expiry,
        expires=access_expiry,
        path=COOKIE_PATH,
        secure=cookie_secure,
        httponly=cookie_httponly,
        samesite=cookie_samesite,
    )

    # Set refresh token cookie
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        max_age=refresh_expiry,
        expires=refresh_expiry,
        path=COOKIE_PATH,
        secure=cookie_secure,
        httponly=cookie_httponly,
        samesite=cookie_samesite,
    )


def clear_auth_cookies(response: Response) -> None:
    """Clear JWT authentication cookies.

    Args:
        response: FastAPI Response object
    """
    cookie_secure = settings.cookie_secure
    cookie_httponly = settings.cookie_httponly
    cookie_samesite = settings.cookie_samesite

    response.delete_cookie(
        key="access_token",
        path=COOKIE_PATH,
        secure=cookie_secure,
        httponly=cookie_httponly,
        samesite=cookie_samesite,
    )
    response.delete_cookie(
        key="refresh_token",
        path=COOKIE_PATH,
        secure=cookie_secure,
        httponly=cookie_httponly,
        samesite=cookie_samesite,
    )
