"""Small cached weather overlay for exposed walking legs."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import lru_cache
from time import monotonic
from zoneinfo import ZoneInfo

import httpx

from app.core.config import Settings, get_settings
from app.models.schema import Segment, TransportMode, WeatherSource

JAKARTA = ZoneInfo("Asia/Jakarta")


@dataclass(frozen=True)
class WeatherObservation:
    observed_at: datetime
    precipitation_mm: float
    weather_code: int


class WeatherEstimator:
    """Fetch current rain once per small map grid and expose its ETA assumption."""

    def __init__(
        self, settings: Settings | None = None, client: httpx.AsyncClient | None = None
    ) -> None:
        self.settings = settings or get_settings()
        self.client = client
        self._cache: dict[tuple[float, float], tuple[float, WeatherObservation]] = {}

    async def enrich_segments(
        self, segments: list[Segment], departure_at: datetime | None
    ) -> list[Segment]:
        walking = [segment for segment in segments if segment.mode is TransportMode.WALK]
        if not walking or not _is_current_trip(departure_at):
            return segments
        coordinates = [point for segment in walking for point in segment.coordinates]
        lng = sum(point[0] for point in coordinates) / len(coordinates)
        lat = sum(point[1] for point in coordinates) / len(coordinates)
        observation = await self._current(lat, lng)
        if observation is None:
            return segments
        factor = _walking_weather_factor(observation)
        return [
            segment.model_copy(
                update={
                    "avg_duration_min": round(segment.avg_duration_min * factor, 2),
                    "weather_factor": factor,
                    "weather_source": WeatherSource.OPEN_METEO,
                    "weather_updated_at": observation.observed_at,
                    "precipitation_mm": observation.precipitation_mm,
                }
            )
            if segment.mode is TransportMode.WALK
            else segment
            for segment in segments
        ]

    async def _current(self, lat: float, lng: float) -> WeatherObservation | None:
        key = (round(lat, 2), round(lng, 2))
        cached = self._cache.get(key)
        if cached and monotonic() - cached[0] < self.settings.weather_cache_ttl_seconds:
            return cached[1]
        params = {
            "latitude": str(lat),
            "longitude": str(lng),
            "current": "precipitation,weather_code",
            "timezone": "Asia/Jakarta",
        }
        try:
            if self.client is not None:
                response = await self.client.get(
                    self.settings.weather_url,
                    params=params,
                    timeout=self.settings.weather_timeout_seconds,
                )
            else:
                async with httpx.AsyncClient() as client:
                    response = await client.get(
                        self.settings.weather_url,
                        params=params,
                        timeout=self.settings.weather_timeout_seconds,
                    )
            response.raise_for_status()
            current = response.json()["current"]
            observation = WeatherObservation(
                observed_at=datetime.fromisoformat(str(current["time"])).replace(tzinfo=JAKARTA),
                precipitation_mm=max(0, float(current["precipitation"])),
                weather_code=int(current["weather_code"]),
            )
            self._cache[key] = (monotonic(), observation)
            return observation
        except (httpx.HTTPError, KeyError, TypeError, ValueError):
            return None


def _walking_weather_factor(observation: WeatherObservation) -> float:
    rain = observation.precipitation_mm
    if rain >= 7.5:
        factor = 1.35
    elif rain >= 2.5:
        factor = 1.25
    elif rain >= 0.2:
        factor = 1.12
    else:
        factor = 1.0
    if observation.weather_code >= 95:
        factor = max(factor, 1.3)
    return factor


def _is_current_trip(departure_at: datetime | None) -> bool:
    if departure_at is None:
        return True
    local = (
        departure_at.replace(tzinfo=JAKARTA)
        if departure_at.tzinfo is None
        else departure_at.astimezone(JAKARTA)
    )
    return abs(local - datetime.now(JAKARTA)) <= timedelta(minutes=30)


@lru_cache
def get_weather_estimator() -> WeatherEstimator:
    return WeatherEstimator()
