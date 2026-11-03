"""Token blacklist for revocation and rotation with Redis backend for multi-worker support"""
import time
import threading
import json
from typing import Set, Dict, Optional, List
from dataclasses import dataclass, field
from contextlib import contextmanager

import redis

from app.core.config import settings
from app.database import SessionLocal
from app.models import TokenFamily


@dataclass
class TokenFamilyData:
    """Track a family of refresh tokens for theft detection"""
    family_id: str
    current_token_jti: str
    created_at: float
    revoked: bool = False
    # Track all JTIs in this family for detection
    seen_jtis: Set[str] = field(default_factory=set)


class TokenBlacklist:
    """Token blacklist with Redis backend for multi-worker support and DB persistence"""

    def __init__(self):
        self._local_blacklist: Set[str] = set()
        self._local_families: Dict[str, TokenFamilyData] = {}
        self._lock = threading.RLock()
        # Cleanup old entries periodically
        self._last_cleanup = time.time()
        self._cleanup_interval = 3600  # 1 hour

        # Redis connection (lazy initialization)
        self._redis: Optional[redis.Redis] = None
        self._redis_available = False
        self._init_redis()

    def _init_redis(self) -> None:
        """Initialize Redis connection if configured"""
        redis_url = getattr(settings, 'redis_url', None)
        if redis_url:
            try:
                self._redis = redis.from_url(
                    redis_url,
                    decode_responses=True,
                    socket_connect_timeout=2,
                    socket_timeout=2,
                    retry_on_timeout=True,
                )
                # Test connection
                self._redis.ping()
                self._redis_available = True
            except Exception:
                self._redis = None
                self._redis_available = False

    def _redis_key_blacklist(self, jti: str) -> str:
        return f"blacklist:{jti}"

    def _redis_key_family(self, family_id: str) -> str:
        return f"token_family:{family_id}"

    def _sync_to_redis(self, jti: str) -> None:
        """Sync a blacklisted JTI to Redis"""
        if self._redis_available and self._redis:
            try:
                # Store with TTL (refresh token expiry + buffer)
                ttl = getattr(settings, 'refresh_token_days', 7) * 24 * 3600 + 3600
                self._redis.setex(self._redis_key_blacklist(jti), ttl, "1")
            except Exception:
                pass  # Fail silently, local blacklist still works

    def _sync_family_to_redis(self, family_id: str, family: TokenFamilyData) -> None:
        """Sync token family to Redis"""
        if self._redis_available and self._redis:
            try:
                ttl = getattr(settings, 'refresh_token_days', 7) * 24 * 3600 + 3600
                data = {
                    "family_id": family.family_id,
                    "current_token_jti": family.current_token_jti,
                    "created_at": family.created_at,
                    "revoked": family.revoked,
                    "seen_jtis": list(family.seen_jtis),
                }
                self._redis.setex(
                    self._redis_key_family(family_id),
                    ttl,
                    json.dumps(data)
                )
            except Exception:
                pass

    def _get_from_redis(self, jti: str) -> bool:
        """Check if JTI is blacklisted in Redis"""
        if self._redis_available and self._redis:
            try:
                return self._redis.exists(self._redis_key_blacklist(jti)) > 0
            except Exception:
                pass
        return False

    def _get_family_from_redis(self, family_id: str) -> Optional[TokenFamilyData]:
        """Get token family from Redis"""
        if self._redis_available and self._redis:
            try:
                data = self._redis.get(self._redis_key_family(family_id))
                if data:
                    d = json.loads(data)
                    family = TokenFamilyData(
                        family_id=d["family_id"],
                        current_token_jti=d["current_token_jti"],
                        created_at=d["created_at"],
                        revoked=d["revoked"],
                        seen_jtis=set(d.get("seen_jtis", [])),
                    )
                    return family
            except Exception:
                pass
        return None

    def add(self, jti: str) -> None:
        """Add a token JTI to the blacklist"""
        with self._lock:
            self._local_blacklist.add(jti)
            self._sync_to_redis(jti)
            self._maybe_cleanup()

    def remove(self, jti: str) -> None:
        """Remove a token JTI from the blacklist (for testing)"""
        with self._lock:
            self._local_blacklist.discard(jti)
            if self._redis_available and self._redis:
                try:
                    self._redis.delete(self._redis_key_blacklist(jti))
                except Exception:
                    pass

    def contains(self, jti: str) -> bool:
        """Check if a token JTI is blacklisted (checks local first, then Redis)"""
        with self._lock:
            if jti in self._local_blacklist:
                return True
            # Check Redis as fallback
            return self._get_from_redis(jti)

    def register_family(self, family_id: str, jti: str) -> None:
        """Register a new token family"""
        with self._lock:
            if family_id not in self._local_families:
                self._local_families[family_id] = TokenFamilyData(
                    family_id=family_id,
                    current_token_jti=jti,
                    created_at=time.time(),
                )
            self._local_families[family_id].seen_jtis.add(jti)
            self._sync_family_to_redis(family_id, self._local_families[family_id])

    def rotate_token(self, family_id: str, old_jti: str, new_jti: str) -> bool:
        """
        Rotate a refresh token within a family.
        Returns True if rotation is valid, False if theft detected.
        """
        with self._lock:
            family = self._local_families.get(family_id)

            # Try to load from Redis if not in local cache
            if not family:
                family = self._get_family_from_redis(family_id)
                if family:
                    self._local_families[family_id] = family

            if not family:
                # Unknown family - treat as potential theft
                return False

            if family.revoked:
                # Family already revoked - theft detected
                return False

            if family.current_token_jti != old_jti:
                # Token reuse detected - THEFT!
                family.revoked = True
                # Blacklist all known tokens in this family
                for jti in family.seen_jtis:
                    self._local_blacklist.add(jti)
                    self._sync_to_redis(jti)
                self._sync_family_to_redis(family_id, family)
                return False

            # Valid rotation
            family.current_token_jti = new_jti
            family.seen_jtis.add(new_jti)
            # Blacklist the old token
            self._local_blacklist.add(old_jti)
            self._sync_to_redis(old_jti)
            self._sync_family_to_redis(family_id, family)
            return True

    def revoke_family(self, family_id: str) -> None:
        """Revoke an entire token family (logout from all devices)"""
        with self._lock:
            family = self._local_families.get(family_id)

            # Try to load from Redis if not in local cache
            if not family:
                family = self._get_family_from_redis(family_id)
                if family:
                    self._local_families[family_id] = family

            if family:
                family.revoked = True
                for jti in family.seen_jtis:
                    self._local_blacklist.add(jti)
                    self._sync_to_redis(jti)
                self._sync_family_to_redis(family_id, family)

    def _maybe_cleanup(self) -> None:
        """Periodically clean up old entries from local cache"""
        now = time.time()
        if now - self._last_cleanup > self._cleanup_interval:
            # Remove old families (older than 30 days)
            cutoff = now - (30 * 24 * 3600)
            expired_families = [
                fid for fid, fam in self._local_families.items()
                if fam.created_at < cutoff
            ]
            for fid in expired_families:
                del self._local_families[fid]
            self._last_cleanup = now

    def __len__(self) -> int:
        with self._lock:
            return len(self._local_blacklist)

    @contextmanager
    def db_session(self):
        """Context manager for database sessions"""
        db = SessionLocal()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def persist_family_to_db(self, family_id: str, user_id: int, current_jti: str | None, revoked: bool) -> None:
        """Persist token family state to database"""
        with self.db_session() as db:
            family = db.query(TokenFamily).filter(TokenFamily.family_id == family_id).first()
            if not family:
                family = TokenFamily(
                    family_id=family_id,
                    user_id=user_id,
                    current_jti=current_jti,
                    revoked=revoked,
                )
                db.add(family)
            else:
                family.current_jti = current_jti
                family.revoked = revoked
                if revoked and not family.revoked_at:
                    family.revoked_at = utc_now()

    def load_user_families(self, user_id: int) -> List[TokenFamilyData]:
        """Load all token families for a user from database"""
        with self.db_session() as db:
            families = db.query(TokenFamily).filter(
                TokenFamily.user_id == user_id
            ).all()

            result = []
            for f in families:
                family_data = TokenFamilyData(
                    family_id=f.family_id,
                    current_token_jti=f.current_jti or "",
                    created_at=f.created_at.timestamp() if f.created_at else time.time(),
                    revoked=f.revoked,
                )
                if f.current_jti:
                    family_data.seen_jtis.add(f.current_jti)
                result.append(family_data)
                # Cache locally
                self._local_families[f.family_id] = family_data

            return result


# Import utc_now for the persist method
from app.models import utc_now

# Global instance
token_blacklist = TokenBlacklist()