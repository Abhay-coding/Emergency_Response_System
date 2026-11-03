"""Audit logging for security events"""
import json
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from enum import Enum


class AuditEventType(str, Enum):
    USER_REGISTERED = "user_registered"
    USER_LOGIN = "user_login"
    USER_LOGIN_FAILED = "user_login_failed"
    USER_LOGOUT = "user_logout"
    TOKEN_REFRESHED = "token_refreshed"
    TOKEN_REVOKED = "token_revoked"
    INCIDENT_CREATED = "incident_created"
    INCIDENT_UPDATED = "incident_updated"
    INCIDENT_DELETED = "incident_deleted"
    INCIDENT_IMAGE_UPLOADED = "incident_image_uploaded"
    INCIDENT_ASSIGNED = "incident_assigned"
    INCIDENT_STATUS_CHANGED = "incident_status_changed"
    ADMIN_ACTION = "admin_action"
    UNAUTHORIZED_ACCESS_ATTEMPT = "unauthorized_access_attempt"
    RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"
    XSS_ATTEMPT = "xss_attempt"
    FILE_UPLOAD_REJECTED = "file_upload_rejected"


class AuditLogger:
    """Structured audit logger for security events"""

    def __init__(self):
        self.logger = logging.getLogger("audit")
        self.logger.setLevel(logging.INFO)
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                '%(asctime)s - AUDIT - %(levelname)s - %(message)s'
            )
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)

    def log(
        self,
        event_type: AuditEventType,
        user_id: Optional[int] = None,
        email: Optional[str] = None,
        ip_address: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        success: bool = True,
    ) -> None:
        """Log an audit event"""
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type.value,
            "user_id": user_id,
            "email": email,
            "ip_address": ip_address,
            "success": success,
            "details": details or {},
        }
        level = logging.INFO if success else logging.WARNING
        self.logger.log(level, json.dumps(event, separators=(',', ':')))


# Global instance
audit_logger = AuditLogger()


def log_security_event(
    event_type: AuditEventType,
    user_id: Optional[int] = None,
    email: Optional[str] = None,
    request: Optional[object] = None,
    details: Optional[Dict[str, Any]] = None,
    success: bool = True,
) -> None:
    """Convenience function to log security events with request context"""
    ip_address = None
    if request and hasattr(request, 'client'):
        ip_address = request.client.host if request.client else None

    audit_logger.log(
        event_type=event_type,
        user_id=user_id,
        email=email,
        ip_address=ip_address,
        details=details,
        success=success,
    )