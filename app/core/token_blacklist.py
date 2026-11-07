"""Token blacklist for revocation and rotation with Redis backend for multi-worker support"""
import time
import threading
import json
import logging
from typing import Set, Dict, Optional, List
from dataclasses import dataclass, field
from contextlib import contextmanager

import redis

from app.core.config import settings
from app.database import SessionLocal
from app.models import TokenFamily, utc_now


logger = logging.getLogger(__name__)


@dataclass
class TokenFamilyData:
    """Track a family of refresh tokens for theft detection"""
    family_id: str
    current_token_jti: str
    created_at: float
    revoked: bool = False
    # Track all JTIs in this family for detection
    seen_jtis: Set[str] = field(default_factory=set)
    # Track theft attempts for gradual response
    theft_attempts: int = 0
    last_theft_attempt: float = 0.0


class TokenBlacklist:
    """Token blacklist with Redis backend for multi-worker support and DB persistence.

    Redis is the source of truth for multi-worker deployments. Local cache is
    only used as a performance optimization and is periodically synced from Redis.
    """

    def __init__(self):
        self._local_blacklist: Set[str] = set()
        self._local_families: Dict[str, TokenFamilyData] = {}
        self._lock = threading.RLock()
        # Cleanup old entries periodically
        self._last_cleanup = time.time()
        self._cleanup_interval = 3600  # 1 hour
        self._last_sync = 0
        self._sync_interval = 60  # Sync local cache from Redis every 60 seconds
        self._cleanup_thread_started = False
        self._cleanup_thread_lock = threading.Lock()

        # Redis connection (lazy initialization)
        self._redis: Optional[redis.Redis] = None
        self._redis_available = False
        self._init_redis()

        # Lua scripts for atomic operations
        self._rotate_token_script = None
        self._revoke_family_script = None
        self._register_family_script = None
        if self._redis_available:
            self._register_lua_scripts()

    def _init_redis(self) -> None:
        """Initialize Redis connection if configured"""
        redis_url = getattr(settings, 'redis_url', None)
        if redis_url:
            try:
                # Enforce TLS in production
                if settings.environment == "production":
                    if not redis_url.startswith("rediss://"):
                        logger.error("Redis URL must use rediss:// (TLS) in production")
                        self._redis = None
                        self._redis_available = False
                        return

                # Configure SSL for TLS connections
                ssl_cert_reqs = None
                if settings.environment == "production":
                    # Require valid certificates in production
                    ssl_cert_reqs = "required"

                self._redis = redis.from_url(
                    redis_url,
                    decode_responses=True,
                    socket_connect_timeout=2,
                    socket_timeout=2,
                    retry_on_timeout=True,
                    ssl_cert_reqs=ssl_cert_reqs,
                )
                # Test connection
                self._redis.ping()
                self._redis_available = True
                logger.info("Redis connection established for token blacklist")
            except Exception as e:
                logger.warning(f"Failed to connect to Redis for token blacklist: {e}")
                self._redis = None
                self._redis_available = False

    def _register_lua_scripts(self) -> None:
        """Register Lua scripts for atomic Redis operations"""
        # Atomic token rotation with theft detection
        rotate_script = """
        local family_key = KEYS[1]
        local blacklist_key = KEYS[2]
        local old_jti = ARGV[1]
        local new_jti = ARGV[2]
        local ttl = ARGV[3]

        local family = redis.call('GET', family_key)
        if not family then
            return {0, "family_not_found"}
        end

        local family_data = cjson.decode(family)
        if family_data.revoked then
            return {0, "family_revoked"}
        end

        -- Initialize theft tracking fields if not present
        family_data.theft_attempts = family_data.theft_attempts or 0
        family_data.last_theft_attempt = family_data.last_theft_attempt or 0

        if family_data.current_token_jti ~= old_jti then
            -- Token reuse detected - potential THEFT!
            -- Don't immediately revoke - track theft attempts instead
            family_data.theft_attempts = family_data.theft_attempts + 1
            family_data.last_theft_attempt = tonumber(ARGV[4]) or 0  -- current timestamp

            -- Only revoke after multiple theft attempts (e.g., 3)
            if family_data.theft_attempts >= 3 then
                family_data.revoked = true
                for _, jti in ipairs(family_data.seen_jtis) do
                    redis.call('SETEX', 'blacklist:' .. jti, ttl, '1')
                end
            end

            -- Blacklist the attempted token to prevent reuse
            redis.call('SETEX', blacklist_key, ttl, '1')
            redis.call('SETEX', family_key, ttl, cjson.encode(family_data))
            return {0, "theft_detected", family_data.theft_attempts}
        end

        -- Valid rotation - reset theft attempts on successful rotation
        family_data.theft_attempts = 0
        family_data.last_theft_attempt = 0
        family_data.current_token_jti = new_jti
        table.insert(family_data.seen_jtis, new_jti)
        redis.call('SETEX', blacklist_key, ttl, '1')
        redis.call('SETEX', family_key, ttl, cjson.encode(family_data))
        return {1, "success"}
        """
        self._rotate_token_script = self._redis.register_script(rotate_script)

        # Atomic family revocation
        revoke_script = """
        local family_key = KEYS[1]
        local ttl = ARGV[1]

        local family = redis.call('GET', family_key)
        if not family then
            return 0
        end

        local family_data = cjson.decode(family)
        family_data.revoked = true
        -- Preserve theft tracking fields
        family_data.theft_attempts = family_data.theft_attempts or 0
        family_data.last_theft_attempt = family_data.last_theft_attempt or 0
        for _, jti in ipairs(family_data.seen_jtis) do
            redis.call('SETEX', 'blacklist:' .. jti, ttl, '1')
        end
        redis.call('SETEX', family_key, ttl, cjson.encode(family_data))
        return 1
        """
        self._revoke_family_script = self._redis.register_script(revoke_script)

        # Atomic family registration using SETNX (set if not exists) to prevent race conditions
        register_family_script = """
        local family_key = KEYS[1]
        local ttl = ARGV[1]
        local family_id = ARGV[2]
        local jti = ARGV[3]
        local created_at = ARGV[4]

        -- Try to set the family key only if it doesn't exist (atomic check-and-set)
        local result = redis.call('SET', family_key, '', 'EX', ttl, 'NX')
        if not result then
            -- Family already exists - race condition detected
            return {0, "family_exists"}
        end

        -- Family key created, now set the actual data
        local family_data = {
            family_id = family_id,
            current_token_jti = jti,
            created_at = tonumber(created_at),
            revoked = false,
            seen_jtis = {jti},
            theft_attempts = 0,
            last_theft_attempt = 0
        }
        redis.call('SET', family_key, cjson.encode(family_data), 'EX', ttl)
        return {1, "success"}
        """
        self._register_family_script = self._redis.register_script(register_family_script)

    def _redis_key_blacklist(self, jti: str) -> str:
        return f"blacklist:{jti}"

    def _redis_key_family(self, family_id: str) -> str:
        return f"token_family:{family_id}"

    def _get_ttl(self) -> int:
        """Get TTL for Redis keys (refresh token expiry + buffer)"""
        return getattr(settings, 'refresh_token_days', 7) * 24 * 3600 + 3600

    def _sync_local_from_redis(self) -> None:
        """Sync local cache from Redis (run periodically)"""
        if not self._redis_available or not self._redis:
            return
        try:
            # We don't sync all keys (too expensive), but we can invalidate local cache
            # by clearing it periodically - the next access will fetch from Redis
            now = time.time()
            if now - self._last_sync > self._sync_interval:
                with self._lock:
                    self._local_blacklist.clear()
                    self._local_families.clear()
                self._last_sync = now
        except Exception as e:
            logger.warning(f"Failed to sync local cache from Redis: {e}")

    def add(self, jti: str) -> None:
        """Add a token JTI to the blacklist (Redis first, then local cache)"""
        ttl = self._get_ttl()

        # Write to Redis first (source of truth)
        if self._redis_available and self._redis:
            try:
                self._redis.setex(self._redis_key_blacklist(jti), ttl, "1")
            except Exception as e:
                logger.error(f"Failed to add JTI to Redis blacklist: {e}")

        # Update local cache
        with self._lock:
            self._local_blacklist.add(jti)
            self._maybe_cleanup()

    def remove(self, jti: str) -> None:
        """Remove a token JTI from the blacklist (for testing)"""
        if self._redis_available and self._redis:
            try:
                self._redis.delete(self._redis_key_blacklist(jti))
            except Exception as e:
                logger.warning(f"Failed to remove JTI from Redis blacklist: {e}")

        with self._lock:
            self._local_blacklist.discard(jti)

    def contains(self, jti: str) -> bool:
        """Check if a token JTI is blacklisted (Redis first, then local cache)"""
        self._sync_local_from_redis()

        # Check Redis first (source of truth for multi-worker)
        if self._redis_available and self._redis:
            try:
                if self._redis.exists(self._redis_key_blacklist(jti)) > 0:
                    with self._lock:
                        self._local_blacklist.add(jti)
                    return True
            except Exception as e:
                logger.warning(f"Failed to check Redis blacklist: {e}")

        # Fallback to local cache
        with self._lock:
            return jti in self._local_blacklist

    def register_family(self, family_id: str, jti: str) -> bool:
        """Register a new token family atomically (Redis first).

        Returns True if registration succeeded, False if family already exists (race condition).
        """
        ttl = self._get_ttl()
        family = TokenFamilyData(
            family_id=family_id,
            current_token_jti=jti,
            created_at=time.time(),
        )
        family.seen_jtis.add(jti)

        # Use atomic Lua script for registration to prevent race conditions
        if self._redis_available and self._redis and self._register_family_script:
            try:
                created_at = str(family.created_at)
                result = self._register_family_script(
                    keys=[self._redis_key_family(family_id)],
                    args=[ttl, family_id, jti, created_at]
                )
                success = bool(result[0])

                if not success:
                    # Family already exists - race condition detected
                    logger.warning(f"Token family registration failed: family already exists (race condition): {family_id}")
                    return False

                # Update local cache
                with self._lock:
                    self._local_families[family_id] = family
                return True
            except Exception as e:
                logger.error(f"Failed to execute atomic family registration: {e}")
                # Fall through to non-atomic logic

        # Fallback: non-atomic registration (when Redis unavailable or script failed)
        # Write to Redis first
        if self._redis_available and self._redis:
            try:
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
            except Exception as e:
                logger.error(f"Failed to register family in Redis: {e}")

        # Update local cache
        with self._lock:
            # Check if family already exists in local cache (race condition)
            if family_id in self._local_families:
                logger.warning(f"Token family registration failed: family already exists in local cache: {family_id}")
                return False
            self._local_families[family_id] = family
        return True

    def rotate_token(self, family_id: str, old_jti: str, new_jti: str) -> bool:
        """
        Rotate a refresh token within a family atomically.
        Returns True if rotation is valid, False if theft detected.
        """
        self._sync_local_from_redis()
        ttl = self._get_ttl()
        current_timestamp = time.time()

        # Use Redis Lua script for atomic operation
        if self._redis_available and self._redis and self._rotate_token_script:
            try:
                result = self._rotate_token_script(
                    keys=[self._redis_key_family(family_id), self._redis_key_blacklist(old_jti)],
                    args=[old_jti, new_jti, ttl, current_timestamp]
                )
                success = bool(result[0])
                theft_attempts = int(result[2]) if len(result) > 2 and result[2] else 0

                # Update local cache based on result
                with self._lock:
                    if success:
                        family = self._local_families.get(family_id)
                        if not family:
                            # Try to load from Redis
                            family = self._get_family_from_redis(family_id)
                            if family:
                                self._local_families[family_id] = family
                        if family:
                            family.current_token_jti = new_jti
                            family.seen_jtis.add(new_jti)
                            family.theft_attempts = 0
                            family.last_theft_attempt = 0.0
                        self._local_blacklist.add(old_jti)
                    else:
                        # Theft detected or family revoked - DON'T immediately revoke in local cache
                        # Instead, update theft attempts counter
                        family = self._local_families.get(family_id)
                        if not family:
                            family = self._get_family_from_redis(family_id)
                        if family:
                            family.theft_attempts = theft_attempts
                            family.last_theft_attempt = current_timestamp
                            # Only revoke if theft_attempts >= 3 (handled by Lua script)
                            if family.theft_attempts >= 3:
                                family.revoked = True
                                for jti in family.seen_jtis:
                                    self._local_blacklist.add(jti)
                            self._local_families[family_id] = family
                        # Always blacklist the attempted token
                        self._local_blacklist.add(old_jti)

                return success
            except Exception as e:
                logger.error(f"Failed to execute atomic token rotation: {e}")
                # Fall through to local-only logic

        # Fallback: local-only logic (when Redis unavailable)
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
                # Token reuse detected - potential THEFT!
                # Don't immediately revoke - track theft attempts instead
                now = time.time()
                family.theft_attempts += 1
                family.last_theft_attempt = now

                # Capture data for sync after releasing lock
                family_data_to_sync = None
                should_revoke = False

                # Only revoke after multiple theft attempts (e.g., 3)
                # or if the theft attempt is from a different context (e.g., different IP)
                # For simplicity, revoke after 3 theft attempts
                if family.theft_attempts >= 3:
                    logger.warning(f"Token family {family_id} revoked after {family.theft_attempts} theft attempts")
                    family.revoked = True
                    should_revoke = True
                    for jti in family.seen_jtis:
                        self._local_blacklist.add(jti)

                # Blacklist the attempted token to prevent reuse
                self._local_blacklist.add(old_jti)
                family_data_to_sync = family

                # Release lock before syncing to Redis
                # (lock will be released when exiting 'with self._lock:')

            # Valid rotation - reset theft attempts on successful rotation
            else:
                family.theft_attempts = 0
                family.last_theft_attempt = 0.0
                family.current_token_jti = new_jti
                family.seen_jtis.add(new_jti)
                # Blacklist the old token
                self._local_blacklist.add(old_jti)
                family_data_to_sync = family

            # Release lock before syncing to Redis
            # (lock will be released when exiting 'with self._lock:')

        # Sync to Redis after releasing lock
        if family_data_to_sync:
            self._sync_family_to_redis(family_id, family_data_to_sync)

            if should_revoke:
                # If revoked due to theft, blacklist all seen JTIs
                for jti in family_data_to_sync.seen_jtis:
                    self._local_blacklist.add(jti)

            return not should_revoke

    def revoke_family(self, family_id: str) -> None:
        """Revoke an entire token family (logout from all devices) atomically"""
        self._sync_local_from_redis()
        ttl = self._get_ttl()

        # Use Redis Lua script for atomic operation
        if self._redis_available and self._redis and self._revoke_family_script:
            try:
                self._revoke_family_script(
                    keys=[self._redis_key_family(family_id)],
                    args=[ttl]
                )
            except Exception as e:
                logger.error(f"Failed to execute atomic family revocation: {e}")
                # Fall through to local logic

        # Update local cache
        family_data_to_sync = None
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
                # Capture data for sync (don't call Redis while holding lock)
                family_data_to_sync = family

        # Sync to Redis after releasing lock
        if family_data_to_sync:
            self._sync_family_to_redis(family_id, family_data_to_sync)

    def _sync_family_to_redis(self, family_id: str, family: TokenFamilyData) -> None:
        """Sync token family to Redis (call WITHOUT holding lock)"""
        if self._redis_available and self._redis:
            try:
                ttl = self._get_ttl()
                data = {
                    "family_id": family.family_id,
                    "current_token_jti": family.current_token_jti,
                    "created_at": family.created_at,
                    "revoked": family.revoked,
                    "seen_jtis": list(family.seen_jtis),
                    "theft_attempts": family.theft_attempts,
                    "last_theft_attempt": family.last_theft_attempt,
                }
                self._redis.setex(
                    self._redis_key_family(family_id),
                    ttl,
                    json.dumps(data)
                )
            except Exception as e:
                logger.warning(f"Failed to sync family to Redis: {e}")

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
                        theft_attempts=d.get("theft_attempts", 0),
                        last_theft_attempt=d.get("last_theft_attempt", 0.0),
                    )
                    return family
            except Exception as e:
                logger.warning(f"Failed to get family from Redis: {e}")
        return None

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

    def start_background_cleanup(self) -> None:
        """Start background thread for periodic cleanup of local cache.

        This method is idempotent - calling it multiple times will only start one thread.
        Should be called during application startup, not at module import time.
        """
        # Use a lock to prevent multiple threads from starting simultaneously
        with self._cleanup_thread_lock:
            if self._cleanup_thread_started:
                logger.debug("Token blacklist background cleanup thread already started")
                return

            def cleanup_worker():
                while True:
                    try:
                        time.sleep(self._cleanup_interval)
                        self._maybe_cleanup()
                        # Also sync local cache from Redis periodically
                        self._sync_local_from_redis()
                    except Exception as e:
                        logger.warning(f"Background cleanup error: {e}")

            cleanup_thread = threading.Thread(target=cleanup_worker, daemon=True, name="token-blacklist-cleanup")
            cleanup_thread.start()
            self._cleanup_thread_started = True
            logger.info("Token blacklist background cleanup thread started")

    def stop_background_cleanup(self) -> None:
        """Stop background cleanup thread (for testing/graceful shutdown).

        Note: This doesn't actually stop the daemon thread (Python doesn't support
        stopping threads), but it marks it as not started so it won't be restarted.
        """
        with self._cleanup_thread_lock:
            self._cleanup_thread_started = False


# Global instance
token_blacklist = TokenBlacklist()

# Background cleanup thread is NOT started at import time.
# Call token_blacklist.start_background_cleanup() during application startup instead.
# This prevents thread proliferation in multi-worker deployments.