"""Road-mode travel-time estimates with bounded live-provider overlays."""

import asyncio
from datetime import date, datetime, timedelta
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
    "https://developer.tomtom.com/routing-api/documentation/"
    "tomtom-maps/v1/calculate-route"
)
GOOGLE_SOURCE_URL = "https://developers.google.com/maps/documentation/routes"


def historical_traffic_factor(segment: Segment, departure_at: datetime | None) -> float:
    """Return a factor relative to a typical scheduled/curated road duration.

    GTFS durations already include ordinary road conditions. The profile should
    therefore move that baseline modestly instead of applying free-flow-to-peak
    congestion a second time.
    """
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
            return 1.04 if peak else 1.0 if shoulder or weekend_busy else 0.96
        return 1.12 if peak else 1.02 if shoulder or weekend_busy else 0.94
    if segment.mode is TransportMode.JAKLINGKO:
        return 1.16 if peak else 1.03 if shoulder or weekend_busy else 0.93
    if segment.mode is TransportMode.ANGKOT:
        return 1.18 if peak else 1.04 if shoulder or weekend_busy else 0.92
    return 1.14 if peak else 1.02 if shoulder or weekend_busy else 0.94


class RoadTrafficEstimator:
    """Enrich selected road legs with one cached provider request per leg.

    TomTom is preferred. Google Routes is an optional fallback protected by
    conservative process-local daily and monthly request budgets. Provider-side
    quotas remain the authoritative hard cap across restarts or multiple workers.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.client = client
        self._flow_cache: dict[tuple[float, float], tuple[float, float, datetime]] = {}
        self._route_cache: dict[
            tuple[str, str, float, float, float, float],
            tuple[float, float, datetime, float],
        ] = {}
        self._semaphore = asyncio.Semaphore(4)
        self._budget_lock = asyncio.Lock()
        self._budget_day: date | None = None
        self._budget_month: tuple[int, int] | None = None
        self._daily_google_calls = 0
        self._monthly_google_calls = 0

    @property
    def live_enabled(self) -> bool:
        return bool(
            self.settings.effective_tomtom_api_key
            or self.settings.effective_google_maps_api_key
        )

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
        delay_min = max(0.0, segment.avg_duration_min * (factor - 1))
        if use_live:
            live = await self._live_route_factor(segment, departure_at)
            if live is not None:
                factor, updated_at, delay_min, source = live
        return segment.model_copy(
            update={
                "avg_duration_min": round(max(0.1, segment.avg_duration_min * factor), 2),
                "traffic_factor": round(factor, 3),
                "traffic_source": source,
                "traffic_updated_at": updated_at,
                "traffic_delay_min": round(max(0.0, delay_min), 1),
            }
        )

    async def _live_route_factor(
        self, segment: Segment, departure_at: datetime
    ) -> tuple[float, datetime, float, TrafficSource] | None:
        if self.settings.effective_tomtom_api_key:
            live = await self._cached_provider_route("tomtom", segment, departure_at)
            if live is not None:
                return (*live, TrafficSource.LIVE_TOMTOM)
            # Flow remains a resilient TomTom fallback for route-summary outages.
            flow = await self._live_flow_factor(segment, departure_at)
            if flow is not None:
                return (*flow, TrafficSource.LIVE_TOMTOM)
        if self.settings.effective_google_maps_api_key:
            live = await self._cached_provider_route("google", segment, departure_at)
            if live is not None:
                return (*live, TrafficSource.LIVE_GOOGLE)
        return None

    async def _cached_provider_route(
        self, provider: str, segment: Segment, departure_at: datetime
    ) -> tuple[float, datetime, float] | None:
        start, end = segment.coordinates[0], segment.coordinates[-1]
        key = (
            provider,
            segment.route_id,
            round(start[0], 4),
            round(start[1], 4),
            round(end[0], 4),
            round(end[1], 4),
        )
        cached = self._route_cache.get(key)
        if cached and monotonic() - cached[0] < self.settings.traffic_cache_ttl_seconds:
            return cached[1], cached[2], cached[3]
        if provider == "google" and not await self._consume_google_budget():
            return None
        try:
            async with self._semaphore:
                if provider == "tomtom":
                    factor, delay = await self._request_tomtom_route(segment)
                else:
                    factor, delay = await self._request_google_route(segment, departure_at)
            updated_at = datetime.now(JAKARTA)
            self._route_cache[key] = (monotonic(), factor, updated_at, delay)
            return factor, updated_at, delay
        except (httpx.HTTPError, KeyError, TypeError, ValueError, ZeroDivisionError, IndexError):
            return None

    async def _request_tomtom_route(self, segment: Segment) -> tuple[float, float]:
        anchors = _route_anchor_points(segment.coordinates)
        path = ":".join(f"{lat},{lng}" for lng, lat in anchors)
        params = {
            "key": self.settings.effective_tomtom_api_key,
            "traffic": "true",
            "computeTravelTimeFor": "all",
            "routeRepresentation": "summaryOnly",
            "travelMode": "motorcycle" if segment.mode is TransportMode.RIDE_HAIL else "car",
        }
        url = f"{self.settings.tomtom_routing_url.rstrip('/')}/calculateRoute/{path}/json"
        payload = await self._get_json(url, params=params)
        summary = payload["routes"][0]["summary"]
        current = float(summary["travelTimeInSeconds"])
        historical = float(summary.get("historicTrafficTravelTimeInSeconds") or 0)
        if current <= 0 or historical <= 0:
            raise ValueError("TomTom route summary omitted comparable travel times")
        factor = min(1.8, max(0.75, current / historical))
        provider_delay = max(0.0, current - historical) / 60
        return factor, provider_delay

    async def _request_google_route(
        self, segment: Segment, departure_at: datetime
    ) -> tuple[float, float]:
        anchors = _route_anchor_points(segment.coordinates)
        body = {
            "origin": _google_waypoint(anchors[0]),
            "destination": _google_waypoint(anchors[-1]),
            "intermediates": [_google_waypoint(point) for point in anchors[1:-1]],
            "travelMode": "DRIVE",
            "routingPreference": "TRAFFIC_AWARE",
            "departureTime": departure_at.isoformat(),
            "languageCode": "id-ID",
            "units": "METRIC",
        }
        headers = {
            "X-Goog-Api-Key": self.settings.effective_google_maps_api_key,
            "X-Goog-FieldMask": "routes.duration,routes.staticDuration",
        }
        payload = await self._post_json(self.settings.google_routes_url, body, headers)
        route = payload["routes"][0]
        current = _duration_seconds(route["duration"])
        free_flow = _duration_seconds(route["staticDuration"])
        if current <= 0 or free_flow <= 0:
            raise ValueError("Google route summary omitted comparable travel times")
        live_free_ratio = current / free_flow
        baseline = _expected_free_flow_ratio(segment, departure_at)
        factor = min(1.8, max(0.75, live_free_ratio / baseline))
        provider_delay = max(0.0, current - free_flow) / 60
        return factor, provider_delay

    async def _live_flow_factor(
        self, segment: Segment, departure_at: datetime
    ) -> tuple[float, datetime, float] | None:
        samples = _traffic_sample_points(segment.coordinates)
        values = await asyncio.gather(*(self._live_factor_at(lat, lng) for lng, lat in samples))
        available = [value for value in values if value is not None]
        if not available:
            return None
        live_free_ratio = sum(value[0] for value in available) / len(available)
        factor = min(
            1.8,
            max(0.75, live_free_ratio / _expected_free_flow_ratio(segment, departure_at)),
        )
        delay = max(0.0, segment.avg_duration_min * (factor - 1))
        return factor, max(value[1] for value in available), delay

    async def _live_factor_at(self, lat: float, lng: float) -> tuple[float, datetime] | None:
        key = (round(lat, 3), round(lng, 3))
        cached = self._flow_cache.get(key)
        if cached and monotonic() - cached[0] < self.settings.traffic_cache_ttl_seconds:
            return cached[1], cached[2]
        try:
            async with self._semaphore:
                payload = await self._get_json(
                    self.settings.tomtom_traffic_url,
                    params={
                        "key": self.settings.effective_tomtom_api_key,
                        "point": f"{lat},{lng}",
                        "unit": "kmph",
                    },
                )
            flow = payload["flowSegmentData"]
            current = float(flow["currentTravelTime"])
            free_flow = float(flow["freeFlowTravelTime"])
            confidence = float(flow.get("confidence", 0))
            if current <= 0 or free_flow <= 0 or confidence < 0.25:
                return None
            ratio = min(3.0, max(0.75, current / free_flow))
            updated_at = datetime.now(JAKARTA)
            self._flow_cache[key] = (monotonic(), ratio, updated_at)
            return ratio, updated_at
        except (httpx.HTTPError, KeyError, TypeError, ValueError, ZeroDivisionError):
            return None

    async def _consume_google_budget(self) -> bool:
        async with self._budget_lock:
            today = datetime.now(JAKARTA).date()
            month = (today.year, today.month)
            if self._budget_day != today:
                self._budget_day = today
                self._daily_google_calls = 0
            if self._budget_month != month:
                self._budget_month = month
                self._monthly_google_calls = 0
            if (
                self._daily_google_calls >= self.settings.google_routes_daily_budget
                or self._monthly_google_calls >= self.settings.google_routes_monthly_budget
            ):
                return False
            self._daily_google_calls += 1
            self._monthly_google_calls += 1
            return True

    async def _get_json(self, url: str, *, params: dict[str, str]) -> dict:
        if self.client is not None:
            response = await self.client.get(
                url, params=params, timeout=self.settings.traffic_timeout_seconds
            )
        else:
            async with httpx.AsyncClient(timeout=self.settings.traffic_timeout_seconds) as client:
                response = await client.get(url, params=params)
        response.raise_for_status()
        return response.json()

    async def _post_json(self, url: str, body: dict, headers: dict[str, str]) -> dict:
        if self.client is not None:
            response = await self.client.post(
                url,
                json=body,
                headers=headers,
                timeout=self.settings.traffic_timeout_seconds,
            )
        else:
            async with httpx.AsyncClient(timeout=self.settings.traffic_timeout_seconds) as client:
                response = await client.post(url, json=body, headers=headers)
        response.raise_for_status()
        return response.json()


def _local_time(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(JAKARTA)
    return value.replace(tzinfo=JAKARTA) if value.tzinfo is None else value.astimezone(JAKARTA)


def _expected_free_flow_ratio(segment: Segment, departure_at: datetime) -> float:
    local = _local_time(departure_at)
    minute = local.hour * 60 + local.minute
    peak = local.weekday() < 5 and (390 <= minute < 570 or 960 <= minute < 1200)
    shoulder = local.weekday() < 5 and (330 <= minute < 630 or 900 <= minute < 1260)
    if peak:
        return 1.38 if segment.mode in {TransportMode.ANGKOT, TransportMode.JAKLINGKO} else 1.3
    if shoulder or (local.weekday() >= 5 and 600 <= minute < 1260):
        return 1.18
    return 1.08


def _route_anchor_points(
    coordinates: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    if len(coordinates) <= 5:
        return coordinates
    indices = [
        0,
        len(coordinates) // 4,
        len(coordinates) // 2,
        len(coordinates) * 3 // 4,
        len(coordinates) - 1,
    ]
    return [coordinates[index] for index in sorted(set(indices))]


def _traffic_sample_points(
    coordinates: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    if len(coordinates) < 8:
        return [coordinates[len(coordinates) // 2]]
    indices = sorted({len(coordinates) // 4, len(coordinates) // 2, len(coordinates) * 3 // 4})
    return [coordinates[index] for index in indices]


def _google_waypoint(point: tuple[float, float]) -> dict:
    lng, lat = point
    return {"location": {"latLng": {"latitude": lat, "longitude": lng}}}


def _duration_seconds(value: str) -> float:
    if not value.endswith("s"):
        raise ValueError("Unsupported duration")
    return float(value[:-1])


@lru_cache
def get_traffic_estimator() -> RoadTrafficEstimator:
    return RoadTrafficEstimator()
