import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from uuid import uuid4

from app.core.audit import log_security_event, AuditEventType
from app.core.rate_limit import limiter
from app.core.security import (
    create_access_token, create_refresh_token, hash_password, verify_password,
    get_token_jti, decode_refresh_token, upgrade_password_hash, is_password_hash_outdated
)
from app.models import CURRENT_PASSWORD_HASH_VERSION
from app.core.token_blacklist import token_blacklist
from app.database import get_db
from app.dependencies import get_current_user
from app.models import Role, User, TokenFamily
from app.schemas import TokenOut, UserCreate, UserOut, RefreshTokenRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register", response_model=UserOut, status_code=201)
@limiter.limit("5/minute")
def register(request: Request, data: UserCreate, db: Session = Depends(get_db)):
    email = str(data.email).lower()

    # Public registration can only create reporter accounts.
    user = User(
        name=data.name,
        email=email,
        password_hash=hash_password(data.password),
        password_hash_version=CURRENT_PASSWORD_HASH_VERSION,
        role=Role.reporter,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        # Simulate same delay as password hash to prevent timing attacks
        verify_password("dummy", DUMMY_PASSWORD_HASH)
        log_security_event(
            AuditEventType.USER_REGISTERED,
            email=email,
            request=request,
            details={"error": "duplicate_email"},
            success=False,
        )
        # Use generic error message to prevent email enumeration
        raise HTTPException(status_code=409, detail="If this email is not registered, a confirmation will be sent")
    db.refresh(user)
    log_security_event(
        AuditEventType.USER_REGISTERED,
        user_id=user.id,
        email=user.email,
        request=request,
        details={"role": user.role.value},
        success=True,
    )
    return user


def get_dummy_password_hash() -> str:
    """Generate a dummy password hash at runtime for constant-time comparison.
    This prevents timing attacks that could reveal whether a user exists.
    """
    # Use a fixed dummy password that will never match a real user
    dummy_password = "dummy-password-for-timing-attack-prevention-32chars!!"
    return hash_password(dummy_password)


# Generate dummy hash at module load time
DUMMY_PASSWORD_HASH = get_dummy_password_hash()


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
        log_security_event(
            AuditEventType.USER_LOGIN_FAILED,
            email=email,
            request=request,
            details={"reason": "user_not_found"},
            success=False,
        )
        raise HTTPException(status_code=401, detail="Incorrect email or password")

    if not verify_password(form.password, user.password_hash):
        log_security_event(
            AuditEventType.USER_LOGIN_FAILED,
            user_id=user.id,
            email=email,
            request=request,
            details={"reason": "invalid_password"},
            success=False,
        )
        raise HTTPException(status_code=401, detail="Incorrect email or password")

    # Check if password hash version is outdated
    if is_password_hash_outdated(user.password_hash_version):
        # Upgrade password hash
        new_hash = upgrade_password_hash(form.password, user.password_hash, user.password_hash_version)
        if new_hash:
            user.password_hash = new_hash
            user.password_hash_version = CURRENT_PASSWORD_HASH_VERSION
            db.commit()
            log_security_event(
                AuditEventType.USER_LOGIN,
                user_id=user.id,
                email=user.email,
                request=request,
                details={"password_hash_upgraded": True, "old_version": user.password_hash_version, "new_version": CURRENT_PASSWORD_HASH_VERSION},
                success=True,
            )
        else:
            # If we can't upgrade (shouldn't happen if we have the password), force password reset
            user.must_reset_password = True
            db.commit()
            log_security_event(
                AuditEventType.USER_LOGIN_FAILED,
                user_id=user.id,
                email=user.email,
                request=request,
                details={"reason": "password_hash_upgrade_failed", "must_reset_password": True},
                success=False,
            )
            raise HTTPException(
                status_code=401,
                detail="Password hash upgrade failed. Please reset your password.",
                headers={"X-Password-Reset-Required": "true"}
            )

    # Also check if user is marked for password reset
    if user.must_reset_password:
        log_security_event(
            AuditEventType.USER_LOGIN_FAILED,
            user_id=user.id,
            email=user.email,
            request=request,
            details={"reason": "password_reset_required"},
            success=False,
        )
        raise HTTPException(
            status_code=401,
            detail="Password reset required. Please use the password reset flow.",
            headers={"X-Password-Reset-Required": "true"}
        )

    # Create a new token family for this login session
    # Retry with new family_id if race condition detected (extremely rare with UUID4)
    max_retries = 3
    for attempt in range(max_retries):
        family_id = str(uuid4())
        access_token = create_access_token(str(user.id))
        refresh_token = create_refresh_token(str(user.id), family_id=family_id)

        # Register the token family with the initial refresh token's JTI
        refresh_jti = get_token_jti(refresh_token)
        if refresh_jti:
            registered = token_blacklist.register_family(family_id, refresh_jti)
            if not registered:
                # Race condition detected - retry with new family_id
                logger.warning(f"Token family race condition on login attempt {attempt + 1}, retrying...")
                continue

            # Store the token family in the database
            token_family = TokenFamily(
                user_id=user.id,
                family_id=family_id,
                current_jti=refresh_jti,
            )
            db.add(token_family)
            db.commit()
            break
    else:
        # All retries failed - extremely unlikely but handle gracefully
        log_security_event(
            AuditEventType.USER_LOGIN_FAILED,
            email=user.email,
            request=request,
            details={"reason": "token_family_registration_failed"},
            success=False,
        )
        raise HTTPException(status_code=500, detail="Failed to create token family, please try again")

    log_security_event(
        AuditEventType.USER_LOGIN,
        user_id=user.id,
        email=user.email,
        request=request,
        details={"family_id": family_id},
        success=True,
    )

    return TokenOut(
        access_token=access_token,
        refresh_token=refresh_token,
    )


@router.post("/refresh", response_model=TokenOut)
@limiter.limit("20/minute")
def refresh_token(
    request: Request,
    data: RefreshTokenRequest,
    db: Session = Depends(get_db),
):
    try:
        payload = decode_refresh_token(data.refresh_token)
        user_id = int(payload["sub"])
        old_jti = payload.get("jti")
        family_id = payload.get("fid")
    except Exception:
        log_security_event(
            AuditEventType.TOKEN_REVOKED,
            request=request,
            details={"reason": "invalid_refresh_token"},
            success=False,
        )
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    # Check if refresh token is blacklisted
    if old_jti and token_blacklist.contains(old_jti):
        log_security_event(
            AuditEventType.TOKEN_REVOKED,
            user_id=user_id,
            request=request,
            details={"reason": "refresh_token_revoked", "jti": old_jti},
            success=False,
        )
        raise HTTPException(status_code=401, detail="Refresh token has been revoked")

    # Also check database for revoked family
    if family_id:
        token_family = db.query(TokenFamily).filter(
            TokenFamily.family_id == family_id,
            TokenFamily.user_id == user_id
        ).first()
        if token_family and token_family.revoked:
            log_security_event(
                AuditEventType.TOKEN_REVOKED,
                user_id=user_id,
                request=request,
                details={"reason": "token_family_revoked", "family_id": family_id},
                success=False,
            )
            raise HTTPException(status_code=401, detail="Token family has been revoked")

    # Create new tokens FIRST to get their JTIs
    new_access_token = create_access_token(str(user.id))
    new_refresh_token = create_refresh_token(str(user.id), family_id=family_id) if family_id else create_refresh_token(str(user.id))

    # Get JTIs from the new tokens
    new_access_jti = get_token_jti(new_access_token)
    new_refresh_jti = get_token_jti(new_refresh_token)

    # Rotate refresh token with theft detection
    if family_id:
        valid_rotation = token_blacklist.rotate_token(family_id, old_jti, new_refresh_jti)
        if not valid_rotation:
            # Theft detected - token_blacklist now tracks theft attempts internally
            # and only revokes after multiple attempts. Just reject this request.
            log_security_event(
                AuditEventType.TOKEN_REVOKED,
                user_id=user_id,
                request=request,
                details={"reason": "token_theft_suspected", "family_id": family_id},
                success=False,
            )
            raise HTTPException(status_code=401, detail="Invalid refresh token")

        # Update database with new JTI
        token_family = db.query(TokenFamily).filter(
            TokenFamily.family_id == family_id
        ).first()
        if token_family:
            token_family.current_jti = new_refresh_jti
            db.commit()
    else:
        # Legacy token without family - just blacklist old token
        if old_jti:
            token_blacklist.add(old_jti)
        # Create a new family for future rotations (retry on race condition)
        max_retries = 3
        for attempt in range(max_retries):
            new_family_id = str(uuid4())
            if new_refresh_jti:
                registered = token_blacklist.register_family(new_family_id, new_refresh_jti)
                if not registered:
                    logger.warning(f"Token family race condition on refresh legacy attempt {attempt + 1}, retrying...")
                    continue
                token_family = TokenFamily(
                    family_id=new_family_id,
                    user_id=user.id,
                    current_jti=new_refresh_jti,
                    revoked=False,
                )
                db.add(token_family)
                db.commit()
                break
        else:
            logger.error("Failed to register token family for legacy token after retries")
            raise HTTPException(status_code=500, detail="Failed to create token family, please try again")

    # Blacklist the old access token
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        old_access_token = auth_header[7:]
        old_access_jti = get_token_jti(old_access_token)
        if old_access_jti:
            token_blacklist.add(old_access_jti)

    log_security_event(
        AuditEventType.TOKEN_REFRESHED,
        user_id=user.id,
        request=request,
        details={"family_id": family_id, "old_jti": old_jti, "new_refresh_jti": new_refresh_jti},
        success=True,
    )

    return TokenOut(
        access_token=new_access_token,
        refresh_token=new_refresh_token,
    )


@router.post("/logout")
@limiter.limit("10/minute")
def logout(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Logout current session - revokes access and refresh tokens"""
    # Get the access token from the request
    auth_header = request.headers.get("authorization", "")
    access_jti = None
    if auth_header.startswith("Bearer "):
        access_token = auth_header[7:]
        access_jti = get_token_jti(access_token)
        if access_jti:
            token_blacklist.add(access_jti)

    # Revoke all active token families for this user (single device logout revokes all sessions)
    active_families = db.query(TokenFamily).filter(
        TokenFamily.user_id == user.id,
        TokenFamily.revoked == False
    ).all()

    revoked_count = 0
    for token_family in active_families:
        token_blacklist.revoke_family(token_family.family_id)
        token_family.revoked = True
        token_family.revoked_at = datetime.now(timezone.utc)
        token_family.current_jti = None
        revoked_count += 1

    if active_families:
        db.commit()
        log_security_event(
            AuditEventType.USER_LOGOUT,
            user_id=user.id,
            email=user.email,
            request=request,
            details={"jti": access_jti, "scope": "all_sessions", "families_revoked": revoked_count},
            success=True,
        )
    else:
        log_security_event(
            AuditEventType.USER_LOGOUT,
            user_id=user.id,
            email=user.email,
            request=request,
            details={"jti": access_jti, "scope": "all_sessions", "note": "no_active_families"},
            success=True,
        )

    return {"message": "Logged out successfully", "sessions_revoked": revoked_count}


@router.post("/logout/all")
@limiter.limit("5/minute")
def logout_all(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Logout from all devices - revokes all token families for the user"""
    # Revoke all active token families for this user
    active_families = db.query(TokenFamily).filter(
        TokenFamily.user_id == user.id,
        TokenFamily.revoked == False
    ).all()

    revoked_count = 0
    for token_family in active_families:
        token_blacklist.revoke_family(token_family.family_id)
        token_family.revoked = True
        token_family.revoked_at = datetime.now(timezone.utc)
        token_family.current_jti = None
        revoked_count += 1

    if active_families:
        db.commit()
        log_security_event(
            AuditEventType.USER_LOGOUT,
            user_id=user.id,
            email=user.email,
            request=request,
            details={"scope": "all_devices", "families_revoked": revoked_count},
            success=True,
        )
        return {"message": f"Logged out from all devices - {revoked_count} token families revoked"}
    else:
        log_security_event(
            AuditEventType.USER_LOGOUT,
            user_id=user.id,
            email=user.email,
            request=request,
            details={"scope": "all_devices", "note": "no_active_families"},
            success=True,
        )
        return {"message": "Logged out from all devices - no active sessions"}


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user
