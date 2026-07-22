"""Road-mode travel-time estimates with an optional live traffic overlay."""

import asyncio
from datetime import datetime, timedelta
from functools import lru_cache
from time import monotonic
from zoneinfo import ZoneInfo

import httpx

from app.core.config import Settings, get_settings
from app.models.schema import Segment, ServiceCategory, TrafficSource, TransportMode

JAKARTA = ZoneInfo("Asia/Jakarta")
ROAD_MODES = {
    TransportMode.ANGKOT,
    TransportMode.TRANSJAKARTA,
    TransportMode.JAKLINGKO,
    TransportMode.RIDE_HAIL,
}
TOMTOM_SOURCE_URL = (
    "https://developer.tomtom.com/traffic-api/documentation/"
    "tomtom-maps/v1/traffic-flow/flow-segment-data"
)


def historical_traffic_factor(segment: Segment, departure_at: datetime | None) -> float:
    """Return a conservative, labeled fallback when no live provider is configured."""
    if segment.mode not in ROAD_MODES:
        return 1.0
    local = _local_time(departure_at)
    minute = local.hour * 60 + local.minute
    weekday = local.weekday() < 5
    peak = weekday and (390 <= minute < 570 or 960 <= minute < 1200)
    shoulder = weekday and (330 <= minute < 630 or 900 <= minute < 1260)
    weekend_busy = not weekday and 600 <= minute < 1260

    if segment.mode is TransportMode.TRANSJAKARTA:
        if segment.service_category is ServiceCategory.MAIN:
            return 1.08 if peak else 1.03 if shoulder or weekend_busy else 1.0
        return 1.24 if peak else 1.1 if shoulder or weekend_busy else 1.0
    if segment.mode is TransportMode.JAKLINGKO:
        return 1.35 if peak else 1.14 if shoulder or weekend_busy else 1.0
    if segment.mode is TransportMode.ANGKOT:
        return 1.4 if peak else 1.16 if shoulder or weekend_busy else 1.0
    return 1.32 if peak else 1.12 if shoulder or weekend_busy else 1.0


class RoadTrafficEstimator:
    """Enrich selected road legs; live calls are bounded and cached by map grid."""

    def __init__(
        self,
        settings: Settings | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.client = client
        self._cache: dict[tuple[float, float], tuple[float, float, datetime]] = {}
        self._semaphore = asyncio.Semaphore(4)

    @property
    def live_enabled(self) -> bool:
        return bool(self.settings.effective_tomtom_api_key)

    async def enrich_segments(
        self, segments: list[Segment], departure_at: datetime | None
    ) -> list[Segment]:
        effective_departure = _local_time(departure_at)
        use_live = self.live_enabled and abs(
            effective_departure - datetime.now(JAKARTA)
        ) <= timedelta(minutes=15)
        tasks = [self._enrich(segment, effective_departure, use_live) for segment in segments]
        return list(await asyncio.gather(*tasks))

    async def _enrich(self, segment: Segment, departure_at: datetime, use_live: bool) -> Segment:
        if segment.mode not in ROAD_MODES:
            return segment
        fallback = historical_traffic_factor(segment, departure_at)
        factor, source, updated_at = fallback, TrafficSource.HISTORICAL_PROFILE, None
        if use_live:
            live = await self._live_factor(segment)
            if live is not None:
                factor, updated_at = live
                source = TrafficSource.LIVE_TOMTOM
        return segment.model_copy(
            update={
                "avg_duration_min": round(segment.avg_duration_min * factor, 2),
                "traffic_factor": round(factor, 3),
                "traffic_source": source,
                "traffic_updated_at": updated_at,
            }
        )

    async def _live_factor(self, segment: Segment) -> tuple[float, datetime] | None:
        lng, lat = segment.coordinates[len(segment.coordinates) // 2]
        key = (round(lat, 3), round(lng, 3))
        cached = self._cache.get(key)
        if cached and monotonic() - cached[0] < self.settings.traffic_cache_ttl_seconds:
            return cached[1], cached[2]
        try:
            async with self._semaphore:
                payload = await self._request(lat, lng)
            flow = payload["flowSegmentData"]
            current = float(flow["currentTravelTime"])
            free_flow = float(flow["freeFlowTravelTime"])
            confidence = float(flow.get("confidence", 0))
            if current <= 0 or free_flow <= 0 or confidence < 0.25:
                return None
            factor = min(3.0, max(0.75, current / free_flow))
            updated_at = datetime.now(JAKARTA)
            self._cache[key] = (monotonic(), factor, updated_at)
            return factor, updated_at
        except (httpx.HTTPError, KeyError, TypeError, ValueError, ZeroDivisionError):
            return None

    async def _request(self, lat: float, lng: float) -> dict:
        params = {
            "key": self.settings.effective_tomtom_api_key,
            "point": f"{lat},{lng}",
            "unit": "kmph",
        }
        if self.client is not None:
            response = await self.client.get(self.settings.tomtom_traffic_url, params=params)
        else:
            async with httpx.AsyncClient(timeout=self.settings.traffic_timeout_seconds) as client:
                response = await client.get(self.settings.tomtom_traffic_url, params=params)
        response.raise_for_status()
        return response.json()


def _local_time(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(JAKARTA)
    return value.replace(tzinfo=JAKARTA) if value.tzinfo is None else value.astimezone(JAKARTA)


@lru_cache
def get_traffic_estimator() -> RoadTrafficEstimator:
    return RoadTrafficEstimator()
