"""Bounded TomTom/Valhalla pedestrian geometry enrichment.

Routing remains usable when the pedestrian service is disabled, saturated, slow, or
unavailable: callers always receive the original straight-line walking segment.
"""

import asyncio
import logging
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import lru_cache
from time import monotonic
from typing import Any

import httpx

from app.core.config import get_settings
from app.models.schema import Segment, TransportMode, WalkingRouteSource

logger = logging.getLogger(__name__)
Coordinate = tuple[float, float]
RequestRoute = Callable[[Coordinate, Coordinate], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class PedestrianRoute:
    coordinates: list[Coordinate]
    duration_min: float
    distance_meters: float
    source: WalkingRouteSource = WalkingRouteSource.VALHALLA


class PedestrianRouter:
    """Bounded, TTL-cached pedestrian router with a free OSM fallback."""

    def __init__(
        self,
        *,
        base_url: str,
        timeout_seconds: float = 2.5,
        max_concurrency: int = 4,
        cache_ttl_seconds: int = 900,
        cache_max_entries: int = 512,
        max_distance_meters: int = 5000,
        tomtom_api_key: str = "",
        tomtom_base_url: str = "https://api.tomtom.com/routing/1",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.cache_ttl_seconds = cache_ttl_seconds
        self.cache_max_entries = cache_max_entries
        self.max_distance_meters = max_distance_meters
        self.tomtom_api_key = tomtom_api_key
        self.tomtom_base_url = tomtom_base_url.rstrip("/")
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._cache: OrderedDict[tuple[Coordinate, Coordinate], tuple[float, PedestrianRoute]] = (
            OrderedDict()
        )
        self._client = client

    @property
    def enabled(self) -> bool:
        return bool(self.tomtom_api_key or self.base_url)

    def clear_cache(self) -> None:
        self._cache.clear()

    async def enrich_segment(self, segment: Segment) -> Segment:
        if not self.enabled or segment.mode is not TransportMode.WALK:
            return segment
        start = segment.coordinates[0]
        end = segment.coordinates[-1]
        key = (_rounded(start), _rounded(end))
        cached = self._get_cached(key)
        if cached is not None:
            return _apply_route(segment, cached)

        try:
            async with self._semaphore:
                cached = self._get_cached(key)
                if cached is None:
                    cached = await self._request_route(start, end)
                    self._put_cached(key, cached)
            return _apply_route(segment, cached)
        except (TimeoutError, httpx.HTTPError, KeyError, TypeError, ValueError, IndexError):
            # Deliberately omit coordinates and request bodies from logs.
            logger.warning("Pedestrian routing unavailable; retaining fallback geometry")
            return segment

    async def enrich_segments(self, segments: list[Segment]) -> list[Segment]:
        return list(await asyncio.gather(*(self.enrich_segment(segment) for segment in segments)))

    async def _request_route(self, start: Coordinate, end: Coordinate) -> PedestrianRoute:
        if self.tomtom_api_key:
            try:
                return await self._request_tomtom_route(start, end)
            except (TimeoutError, httpx.HTTPError, KeyError, TypeError, ValueError, IndexError):
                if not self.base_url:
                    raise
                logger.warning("TomTom pedestrian routing unavailable; trying Valhalla")
        return await self._request_valhalla_route(start, end)

    async def _request_valhalla_route(
        self, start: Coordinate, end: Coordinate
    ) -> PedestrianRoute:
        payload = {
            "locations": [
                {"lat": start[1], "lon": start[0], "type": "break"},
                {"lat": end[1], "lon": end[0], "type": "break"},
            ],
            "costing": "pedestrian",
            "units": "kilometers",
        }
        if self._client is not None:
            response = await self._client.post(
                f"{self.base_url}/route", json=payload, timeout=self.timeout_seconds
            )
        else:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/route", json=payload, timeout=self.timeout_seconds
                )
        response.raise_for_status()
        trip = response.json()["trip"]
        legs = trip["legs"]
        coordinates: list[Coordinate] = []
        for leg in legs:
            decoded = decode_polyline6(leg["shape"])
            coordinates.extend(decoded if not coordinates else decoded[1:])
        summary = trip["summary"]
        distance_meters = float(summary["length"]) * 1000
        duration_min = float(summary["time"]) / 60
        if len(coordinates) < 2 or distance_meters <= 0 or duration_min <= 0:
            raise ValueError("Pedestrian route was empty")
        if distance_meters > self.max_distance_meters:
            raise ValueError("Pedestrian route exceeded configured bound")
        return PedestrianRoute(
            coordinates, duration_min, distance_meters, WalkingRouteSource.VALHALLA
        )

    async def _request_tomtom_route(
        self, start: Coordinate, end: Coordinate
    ) -> PedestrianRoute:
        path = f"{start[1]},{start[0]}:{end[1]},{end[0]}"
        params = {
            "key": self.tomtom_api_key,
            "travelMode": "pedestrian",
            "routeRepresentation": "polyline",
            "computeTravelTimeFor": "all",
            "language": "id-ID",
        }
        url = f"{self.tomtom_base_url}/calculateRoute/{path}/json"
        if self._client is not None:
            response = await self._client.get(url, params=params, timeout=self.timeout_seconds)
        else:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, params=params, timeout=self.timeout_seconds)
        response.raise_for_status()
        route = response.json()["routes"][0]
        coordinates: list[Coordinate] = []
        for leg in route["legs"]:
            decoded = [
                (float(point["longitude"]), float(point["latitude"]))
                for point in leg["points"]
            ]
            coordinates.extend(decoded if not coordinates else decoded[1:])
        summary = route["summary"]
        distance_meters = float(summary["lengthInMeters"])
        duration_min = float(summary["travelTimeInSeconds"]) / 60
        if len(coordinates) < 2 or distance_meters <= 0 or duration_min <= 0:
            raise ValueError("Pedestrian route was empty")
        if distance_meters > self.max_distance_meters:
            raise ValueError("Pedestrian route exceeded configured bound")
        return PedestrianRoute(
            coordinates, duration_min, distance_meters, WalkingRouteSource.TOMTOM
        )

    def _get_cached(self, key: tuple[Coordinate, Coordinate]) -> PedestrianRoute | None:
        entry = self._cache.get(key)
        if entry is None:
            return None
        stored_at, route = entry
        if monotonic() - stored_at >= self.cache_ttl_seconds:
            del self._cache[key]
            return None
        self._cache.move_to_end(key)
        return route

    def _put_cached(self, key: tuple[Coordinate, Coordinate], route: PedestrianRoute) -> None:
        self._cache[key] = (monotonic(), route)
        self._cache.move_to_end(key)
        while len(self._cache) > self.cache_max_entries:
            self._cache.popitem(last=False)


@lru_cache
def get_pedestrian_router() -> PedestrianRouter:
    settings = get_settings()
    return PedestrianRouter(
        base_url=settings.pedestrian_router_url,
        timeout_seconds=settings.pedestrian_router_timeout_seconds,
        max_concurrency=settings.pedestrian_router_max_concurrency,
        cache_ttl_seconds=settings.pedestrian_router_cache_ttl_seconds,
        cache_max_entries=settings.pedestrian_router_cache_max_entries,
        max_distance_meters=settings.pedestrian_router_max_distance_meters,
        tomtom_api_key=settings.effective_tomtom_api_key,
        tomtom_base_url=settings.tomtom_routing_url,
    )


def invalidate_pedestrian_cache() -> None:
    if get_pedestrian_router.cache_info().currsize:
        get_pedestrian_router().clear_cache()


def decode_polyline6(shape: str) -> list[Coordinate]:
    """Decode Valhalla's precision-six encoded polyline into GeoJSON order."""
    index = lat = lng = 0
    coordinates: list[Coordinate] = []
    while index < len(shape):
        deltas: list[int] = []
        for _ in range(2):
            result = shift = 0
            while True:
                value = ord(shape[index]) - 63
                index += 1
                result |= (value & 0x1F) << shift
                shift += 5
                if value < 0x20:
                    break
            deltas.append(~(result >> 1) if result & 1 else result >> 1)
        lat += deltas[0]
        lng += deltas[1]
        coordinates.append((lng / 1_000_000, lat / 1_000_000))
    return coordinates


def _apply_route(segment: Segment, route: PedestrianRoute) -> Segment:
    return segment.model_copy(
        update={
            "coordinates": route.coordinates,
            "avg_duration_min": round(max(0.1, route.duration_min), 1),
            "walking_distance_meters": round(route.distance_meters),
            "walking_route_source": route.source,
        }
    )


def _rounded(coordinate: Coordinate) -> Coordinate:
    # About 0.1 m precision: stable cache keys without changing routed endpoints.
    return round(coordinate[0], 6), round(coordinate[1], 6)
