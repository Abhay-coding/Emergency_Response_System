from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Settings(BaseSettings):
    app_name: str = "Campus Emergency Response System"
    database_url: str = "sqlite:///./emergency.db"
    upload_dir: str = "uploads"
    max_upload_size_mb: int = 5
    # JWT secret MUST be set via environment variable - no default for security
    jwt_secret: str
    access_token_minutes: int = 60
    refresh_token_days: int = 7
    # Rate limiting
    rate_limit_requests: int = 100
    rate_limit_window: int = 60

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
