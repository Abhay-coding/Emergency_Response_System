from fastapi import Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
import jwt
import ipaddress

from app.core.security import decode_access_token, get_token_jti
from app.core.token_blacklist import token_blacklist
from app.database import get_db
from app.models import Role, User
from app.core.config import settings

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


def get_client_ip(request: Request) -> str:
    """Get the real client IP address, considering trusted proxies.

    Only trust X-Forwarded-For if the direct client is in trusted_proxies.
    This prevents IP spoofing by malicious clients sending fake headers.
    """
    trusted_proxies = settings.trusted_proxies
    direct_client_ip = request.client.host if request.client else "unknown"

    # If no trusted proxies configured, use direct client IP
    if not trusted_proxies:
        return direct_client_ip

    # Verify the direct client is a trusted proxy
    direct_client_trusted = False
    try:
        direct_ip = ipaddress.ip_address(direct_client_ip)
        for proxy_cidr in trusted_proxies:
            try:
                network = ipaddress.ip_network(proxy_cidr, strict=False)
                if direct_ip in network:
                    direct_client_trusted = True
                    break
            except ValueError:
                # Invalid CIDR, skip
                continue
    except ValueError:
        # Invalid direct client IP
        pass

    if not direct_client_trusted:
        # Direct client is not a trusted proxy - don't trust X-Forwarded-For
        return direct_client_ip

    # Direct client is trusted - parse X-Forwarded-For header
    xff = request.headers.get("X-Forwarded-For")
    if not xff:
        return direct_client_ip

    # Split by comma and strip spaces
    ips = [ip.strip() for ip in xff.split(",")]

    # Number of hops to trust (from the right)
    trusted_hops = settings.proxy_headers_trusted_hops
    if trusted_hops <= 0 or trusted_hops > len(ips):
        trusted_hops = len(ips)

    # The client IP is the first untrusted IP from the right
    # Proxies are added from left to right, so we skip the rightmost trusted_hops
    client_ip_idx = len(ips) - trusted_hops
    if client_ip_idx < 0:
        client_ip_idx = 0

    client_ip = ips[client_ip_idx]

    # Validate it's a valid IP
    try:
        ipaddress.ip_address(client_ip)
        return client_ip
    except ValueError:
        return direct_client_ip


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

    # Fall back to IP address (using trusted proxy detection)
    return f"ip:{get_client_ip(request)}"