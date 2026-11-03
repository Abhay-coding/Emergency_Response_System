from fastapi import Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
import jwt

from app.core.security import decode_access_token, get_token_jti
from app.core.token_blacklist import token_blacklist
from app.database import get_db
from app.models import Role, User
from app.core.config import settings

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    try:
        payload = decode_access_token(token)
        user_id = int(payload["sub"])
    except (jwt.InvalidTokenError, ValueError, KeyError):
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    # Check if token is blacklisted
    jti = payload.get("jti")
    if jti and token_blacklist.contains(jti):
        raise HTTPException(status_code=401, detail="Token has been revoked")

    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


def get_optional_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User | None:
    """Get current user if authenticated, otherwise return None"""
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        return None

    token = auth_header[7:]
    try:
        payload = decode_access_token(token)
        user_id = int(payload["sub"])

        # Check if token is blacklisted
        jti = payload.get("jti")
        if jti and token_blacklist.contains(jti):
            return None

        user = db.get(User, user_id)
        return user
    except (jwt.InvalidTokenError, ValueError, KeyError):
        return None


def require_roles(*roles: Role):
    def checker(user: User = Depends(get_current_user)):
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return user
    return checker


# Rate limiting key function - use user ID if authenticated, otherwise IP
def get_rate_limit_key(request: Request) -> str:
    """Get rate limit key based on user ID or IP"""
    # Try to get user from request state (set by auth middleware)
    if hasattr(request.state, "user") and request.state.user:
        return f"user:{request.state.user.id}"

    # Fall back to IP address
    from slowapi.util import get_remote_address
    return f"ip:{get_remote_address(request)}"