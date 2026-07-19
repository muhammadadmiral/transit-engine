from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Transit Engine"
    app_env: str = "development"
    port: int = 7860
    database_url: str = "postgresql+asyncpg://postgres:postgres@db:5432/transit_engine"
    cors_allowed_origins: str = "http://localhost:3000"
    data_refresh_secret: str = ""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allowed_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()

