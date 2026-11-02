"""Token blacklist for revocation and rotation"""
import time
import threading
from typing import Set, Dict, Optional
from dataclasses import dataclass, field


@dataclass
class TokenFamily:
    """Track a family of refresh tokens for theft detection"""
    family_id: str
    current_token_jti: str
    created_at: float
    revoked: bool = False
    # Track all JTIs in this family for detection
    seen_jtis: Set[str] = field(default_factory=set)


class TokenBlacklist:
    """Thread-safe token blacklist with family tracking for theft detection"""

    def __init__(self):
        self._blacklist: Set[str] = set()
        self._families: Dict[str, TokenFamily] = {}
        self._lock = threading.RLock()
        # Cleanup old entries periodically
        self._last_cleanup = time.time()
        self._cleanup_interval = 3600  # 1 hour

    def add(self, jti: str) -> None:
        """Add a token JTI to the blacklist"""
        with self._lock:
            self._blacklist.add(jti)
            self._maybe_cleanup()

    def remove(self, jti: str) -> None:
        """Remove a token JTI from the blacklist (for testing)"""
        with self._lock:
            self._blacklist.discard(jti)

    def contains(self, jti: str) -> bool:
        """Check if a token JTI is blacklisted"""
        with self._lock:
            return jti in self._blacklist

    def register_family(self, family_id: str, jti: str) -> None:
        """Register a new token family"""
        with self._lock:
            if family_id not in self._families:
                self._families[family_id] = TokenFamily(
                    family_id=family_id,
                    current_token_jti=jti,
                    created_at=time.time(),
                )
            self._families[family_id].seen_jtis.add(jti)

    def rotate_token(self, family_id: str, old_jti: str, new_jti: str) -> bool:
        """
        Rotate a refresh token within a family.
        Returns True if rotation is valid, False if theft detected.
        """
        with self._lock:
            family = self._families.get(family_id)
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
                    self._blacklist.add(jti)
                return False

            # Valid rotation
            family.current_token_jti = new_jti
            family.seen_jtis.add(new_jti)
            # Blacklist the old token
            self._blacklist.add(old_jti)
            return True

    def revoke_family(self, family_id: str) -> None:
        """Revoke an entire token family (logout from all devices)"""
        with self._lock:
            family = self._families.get(family_id)
            if family:
                family.revoked = True
                for jti in family.seen_jtis:
                    self._blacklist.add(jti)

    def _maybe_cleanup(self) -> None:
        """Periodically clean up old entries"""
        now = time.time()
        if now - self._last_cleanup > self._cleanup_interval:
            # Remove old families (older than 30 days)
            cutoff = now - (30 * 24 * 3600)
            expired_families = [
                fid for fid, fam in self._families.items()
                if fam.created_at < cutoff
            ]
            for fid in expired_families:
                del self._families[fid]
            self._last_cleanup = now

    def __len__(self) -> int:
        with self._lock:
            return len(self._blacklist)


# Global instance
token_blacklist = TokenBlacklist()