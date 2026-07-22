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
    pedestrian_router_url: str = "https://valhalla1.openstreetmap.de"
    pedestrian_router_timeout_seconds: float = 5.0
    pedestrian_router_max_concurrency: int = 2
    pedestrian_router_cache_ttl_seconds: int = 900
    pedestrian_router_cache_max_entries: int = 512
    pedestrian_router_max_distance_meters: int = 5000
    ride_hail_router_max_distance_meters: int = 15000
    geocoder_nominatim_url: str = "https://nominatim.openstreetmap.org"
    geocoder_photon_url: str = "https://photon.komoot.io"
    geocoder_user_agent: str = "TransHub-Jabodetabek/0.1"
    geocoder_timeout_seconds: float = 8.0
    geocoder_nominatim_interval_seconds: float = 1.0
    tomtom_api_key: SecretStr = SecretStr("")
    tomtom_search_url: str = "https://api.tomtom.com/search/2"
    tomtom_routing_url: str = "https://api.tomtom.com/routing/1"
    tomtom_matrix_url: str = "https://api.tomtom.com/routing/matrix/2"
    tomtom_snap_to_roads_url: str = "https://api.tomtom.com/snapToRoads/1"
    tomtom_traffic_api_key: SecretStr = SecretStr("")
    tomtom_traffic_url: str = (
        "https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/10/json"
    )
    traffic_timeout_seconds: float = 2.5
    traffic_cache_ttl_seconds: int = 300
    weather_url: str = "https://api.open-meteo.com/v1/forecast"
    weather_timeout_seconds: float = 2.5
    weather_cache_ttl_seconds: int = 600
    routing_max_concurrency: int = 1

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

    @property
    def effective_tomtom_api_key(self) -> str:
        """Use one TomTom key while keeping the old traffic-only variable compatible."""
        return (
            self.tomtom_api_key.get_secret_value() or self.tomtom_traffic_api_key.get_secret_value()
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
