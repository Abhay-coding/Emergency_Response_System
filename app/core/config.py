from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional
import os
from functools import lru_cache
from pydantic import field_validator
import secrets

from app.core.constants import (
    DEFAULT_DB_POOL_SIZE,
    DEFAULT_DB_MAX_OVERFLOW,
    DEFAULT_DB_POOL_TIMEOUT,
    DEFAULT_DB_POOL_RECYCLE_SECONDS,
    DEFAULT_MAX_UPLOAD_SIZE_MB,
    DEFAULT_ALERT_ACK_SECONDS,
    DEFAULT_CAMPUS_TIMEZONE,
    DEFAULT_ACCESS_TOKEN_MINUTES,
    DEFAULT_REFRESH_TOKEN_DAYS,
    DEFAULT_RATE_LIMIT_REQUESTS,
    DEFAULT_RATE_LIMIT_WINDOW_SECONDS,
    DEFAULT_CORS_ORIGINS,
    DEFAULT_ALLOWED_METHODS,
    DEFAULT_ALLOWED_HEADERS,
    DEFAULT_EXPOSE_HEADERS,
    DEFAULT_LOG_LEVEL,
    DEFAULT_LOG_FORMAT,
    DEFAULT_CAMPUS_TIMEZONE as DEFAULT_TIMEZONE,
)


class Settings(BaseSettings):
    # Application
    app_name: str = "Campus Medical Assistance"
    environment: str = "development"  # development, staging, production
    debug: bool = False

    # Database
    database_url: str = "sqlite:///./emergency.db"
    # For PostgreSQL: postgresql+psycopg://user:pass@host:5432/dbname
    # For SQLite: sqlite:///./emergency.db

    # Database connection pool settings (for PostgreSQL)
    db_pool_size: int = DEFAULT_DB_POOL_SIZE
    db_max_overflow: int = DEFAULT_DB_MAX_OVERFLOW
    db_pool_timeout: int = DEFAULT_DB_POOL_TIMEOUT
    db_pool_recycle: int = DEFAULT_DB_POOL_RECYCLE_SECONDS

    # File uploads
    upload_dir: str = "uploads"
    max_upload_size_mb: int = DEFAULT_MAX_UPLOAD_SIZE_MB
    alert_ack_seconds: int = DEFAULT_ALERT_ACK_SECONDS
    campus_emergency_phone: Optional[str] = None
    backup_phone: Optional[str] = None
    notification_mode: str = "simulation"  # simulation, sns
    aws_region: Optional[str] = None
    aws_sqs_queue_url: Optional[str] = None
    data_api_enabled: bool = False
    dynamo_demo_enabled: bool = False
    campus_timezone: str = DEFAULT_CAMPUS_TIMEZONE

    # JWT
    # JWT secret MUST be set via environment variable - no default for security
    jwt_secret: Optional[str] = None
    access_token_minutes: int = DEFAULT_ACCESS_TOKEN_MINUTES
    refresh_token_days: int = DEFAULT_REFRESH_TOKEN_DAYS

    # Guest token secret (for medical alerts guest access)
    # Should be different from jwt_secret for key separation
    # Defaults to jwt_secret if not set (backward compatibility)
    guest_token_secret: Optional[str] = None

    # Redis (for token blacklist, rate limiting, caching)
    redis_url: Optional[str] = None  # redis://localhost:6379/0

    # Rate limiting
    rate_limit_requests: int = DEFAULT_RATE_LIMIT_REQUESTS
    rate_limit_window: int = DEFAULT_RATE_LIMIT_WINDOW_SECONDS

    # CORS
    cors_origins: list[str] = DEFAULT_CORS_ORIGINS

    # Development CORS origins (only used when environment != production and cors_origins is empty)
    dev_cors_origins: list[str] = ["http://127.0.0.1:5500", "http://localhost:5500"]

    # Security
    # For production, MUST be set to your specific domain(s) - no wildcard allowed
    allowed_hosts: list[str] = []

    # Trusted proxy configuration for real IP detection
    # Set to list of trusted proxy IPs/CIDRs (e.g., ["10.0.0.0/8", "172.16.0.0/12"])
    # When set, X-Forwarded-For header will be used to get real client IP
    trusted_proxies: list[str] = []

    # Number of trusted proxy hops (for X-Forwarded-For parsing)
    proxy_headers_trusted_hops: int = 1

    # Cookie security settings
    # In production, must be True (HTTPS only). In development, can be False for localhost HTTP.
    cookie_secure: bool = True
    cookie_httponly: bool = True
    cookie_samesite: str = "strict"  # strict, lax, or none

    # Logging
    log_level: str = DEFAULT_LOG_LEVEL
    log_format: str = DEFAULT_LOG_FORMAT  # json or text

    # Monitoring
    enable_metrics: bool = True
    metrics_path: str = "/metrics"

    # Health check
    health_check_path: str = "/health"

    @field_validator('jwt_secret')
    @classmethod
    def validate_jwt_secret(cls, v: str) -> str:
        """Validate JWT secret has sufficient entropy and length"""
        if not v:
            return v
        if len(v) < 32:
            raise ValueError('JWT secret must be at least 32 characters long')

        # Check for minimum entropy - reject common weak secrets
        weak_secrets = {
            'secret', 'secretkey', 'jwtsecret', 'mysecret', 'test',
            'changeme', 'password', 'admin', 'development', 'production',
        }
        if v.lower() in weak_secrets:
            raise ValueError('JWT secret is too weak (common value)')

        # Check for repeated characters (low entropy)
        unique_chars = len(set(v))
        if unique_chars < 8:
            raise ValueError('JWT secret has insufficient entropy (too few unique characters)')

        # Warn if not using a cryptographically secure random secret
        if len(v) < 64:
            import logging
            logging.getLogger(__name__).warning(
                'JWT secret is less than 64 characters. '
                'Consider using a cryptographically secure random secret (e.g., secrets.token_urlsafe(64))'
            )

        return v

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance"""
    return Settings()


settings = get_settings()

if not settings.jwt_secret and os.getenv("APP_SECRET_ARN"):
    import json
    import boto3
    secret = json.loads(boto3.client("secretsmanager").get_secret_value(SecretId=os.environ["APP_SECRET_ARN"])["SecretString"])
    settings.jwt_secret = secret["jwt_secret"]
    settings.guest_token_secret = secret.get("guest_token_secret", settings.jwt_secret)
