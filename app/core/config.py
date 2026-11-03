from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional
from functools import lru_cache


class Settings(BaseSettings):
    # Application
    app_name: str = "Campus Emergency Response System"
    environment: str = "development"  # development, staging, production
    debug: bool = False

    # Database
    database_url: str = "sqlite:///./emergency.db"
    # For PostgreSQL: postgresql+psycopg://user:pass@host:5432/dbname
    # For SQLite: sqlite:///./emergency.db

    # Database connection pool settings (for PostgreSQL)
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_timeout: int = 30
    db_pool_recycle: int = 3600

    # File uploads
    upload_dir: str = "uploads"
    max_upload_size_mb: int = 5

    # JWT
    # JWT secret MUST be set via environment variable - no default for security
    jwt_secret: str
    access_token_minutes: int = 60
    refresh_token_days: int = 7

    # Redis (for token blacklist, rate limiting, caching)
    redis_url: Optional[str] = None  # redis://localhost:6379/0

    # Rate limiting
    rate_limit_requests: int = 100
    rate_limit_window: int = 60

    # CORS
    cors_origins: list[str] = ["http://127.0.0.1:5500", "http://localhost:5500"]

    # Security
    # For production, set to your domain(s)
    allowed_hosts: list[str] = ["*"]

    # Logging
    log_level: str = "INFO"
    log_format: str = "json"  # json or text

    # Monitoring
    enable_metrics: bool = True
    metrics_path: str = "/metrics"

    # Health check
    health_check_path: str = "/health"

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