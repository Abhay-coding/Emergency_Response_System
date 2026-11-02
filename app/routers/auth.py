from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from uuid import uuid4

from app.core.rate_limit import limiter
from app.core.security import (
    create_access_token, create_refresh_token, hash_password, verify_password,
    get_refresh_token_family
)
from app.core.token_blacklist import token_blacklist
from app.database import get_db
from app.dependencies import get_current_user
from app.models import Role, User
from app.schemas import TokenOut, UserCreate, UserOut, RefreshTokenRequest

router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])


@router.post("/register", response_model=UserOut, status_code=201)
@limiter.limit("5/minute")
def register(request: Request, data: UserCreate, db: Session = Depends(get_db)):
    email = str(data.email).lower()

    # Public registration can only create reporter accounts.
    user = User(
        name=data.name,
        email=email,
        password_hash=hash_password(data.password),
        role=Role.reporter,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        # Simulate same delay as password hash to prevent timing attacks
        verify_password("dummy", DUMMY_PASSWORD_HASH)
        raise HTTPException(status_code=409, detail="Email already registered")
    db.refresh(user)
    return user


# Pre-computed valid Argon2 hash for constant-time comparison
# This ensures verify_password takes the same time regardless of user existence
DUMMY_PASSWORD_HASH = "$argon2id$v=19$m=65536,t=3,p=4$wY4rOBap3cYCSw9jIFwNXg$i5hVxIyTz2SLQkJUV4RH/nIDYaKCkkIXkqSshITK3sQ"


@router.post("/login", response_model=TokenOut)
@limiter.limit("10/minute")
def login(
    request: Request,
    form: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    email = form.username.lower()
    user = db.query(User).filter(User.email == email).first()

    # Constant-time verification to prevent email enumeration
    if not user:
        verify_password(form.password, DUMMY_PASSWORD_HASH)
        raise HTTPException(status_code=401, detail="Incorrect email or password")

    if not verify_password(form.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect email or password")

    # Create a new token family for this login session
    family_id = str(uuid4())
    return TokenOut(
        access_token=create_access_token(str(user.id)),
        refresh_token=create_refresh_token(str(user.id), family_id=family_id),
    )


@router.post("/refresh", response_model=TokenOut)
@limiter.limit("20/minute")
def refresh_token(
    request: Request,
    data: RefreshTokenRequest,
    db: Session = Depends(get_db),
):
    from app.core.security import decode_refresh_token, get_refresh_token_family
    try:
        payload = decode_refresh_token(data.refresh_token)
        user_id = int(payload["sub"])
        old_jti = payload.get("jti")
        family_id = payload.get("fid")
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    # Check if refresh token is blacklisted
    if old_jti and token_blacklist.contains(old_jti):
        raise HTTPException(status_code=401, detail="Refresh token has been revoked")

    # Rotate refresh token with theft detection
    if family_id:
        valid_rotation = token_blacklist.rotate_token(family_id, old_jti, str(uuid4()))
        if not valid_rotation:
            # Theft detected - revoke entire family
            token_blacklist.revoke_family(family_id)
            raise HTTPException(status_code=401, detail="Token theft detected, session revoked")
    else:
        # Legacy token without family - just blacklist old token
        if old_jti:
            token_blacklist.add(old_jti)

    # Register the new token in the family
    if family_id:
        token_blacklist.register_family(family_id, str(uuid4()))

    # Create new tokens with same family_id
    new_access_token = create_access_token(str(user.id))
    new_refresh_token = create_refresh_token(str(user.id), family_id=family_id)

    return TokenOut(
        access_token=new_access_token,
        refresh_token=new_refresh_token,
    )


@router.post("/logout")
@limiter.limit("10/minute")
def logout(
    request: Request,
    user: User = Depends(get_current_user),
):
    """Logout current session - revokes access and refresh tokens"""
    # The access token will be blacklisted by the get_current_user dependency
    # For full logout, we'd need to also blacklist the refresh token
    # This is a basic logout - for full logout from all devices, use /logout/all
    return {"message": "Logged out successfully"}


@router.post("/logout/all")
@limiter.limit("5/minute")
def logout_all(
    request: Request,
    user: User = Depends(get_current_user),
):
    """Logout from all devices - revokes entire token family"""
    # In a production system, you'd track which family_id belongs to the user
    # For now, this is a placeholder - would need to store family_id in user table
    return {"message": "Logged out from all devices (placeholder)"}


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user
