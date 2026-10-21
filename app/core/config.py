from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Campus Emergency Response System"
    database_url: str = "sqlite:///./emergency.db"
    upload_dir: str = "uploads"
    max_upload_size_mb: int = 5
    jwt_secret: str = "development-only-change-me"
    access_token_minutes: int = 60

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )


settings = Settings()
