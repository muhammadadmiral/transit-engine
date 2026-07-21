from functools import lru_cache

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Transit Engine"
    app_env: str = "development"
    port: int = 7860
    database_url: str = "postgresql+asyncpg://postgres:postgres@db:5432/transit_engine"
    cors_allowed_origins: str = "http://localhost:3000"
    data_refresh_secret: str = ""
    transjakarta_gtfs_url: str = "https://gtfs.transjakarta.co.id/files/file_gtfs.zip"
    nvidia_nim_api_key: SecretStr = SecretStr("")
    nvidia_nim_base_url: str = "https://integrate.api.nvidia.com/v1"
    nvidia_nim_model: str = "meta/llama-3.3-70b-instruct"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @field_validator("database_url", mode="before")
    @classmethod
    def use_asyncpg_driver(cls, value: str) -> str:
        """Accept the standard PostgreSQL URL supplied by managed integrations."""
        if value.startswith("postgres://"):
            return "postgresql+asyncpg://" + value.removeprefix("postgres://")
        if value.startswith("postgresql://"):
            return "postgresql+asyncpg://" + value.removeprefix("postgresql://")
        return value

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allowed_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
