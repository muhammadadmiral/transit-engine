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


@dataclass(frozen=True)
class PedestrianMeasure:
    duration_min: float
    distance_meters: float
    routed: bool = True


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
        ride_hail_max_distance_meters: int = 10000,
        tomtom_api_key: str = "",
        tomtom_base_url: str = "https://api.tomtom.com/routing/1",
        tomtom_matrix_url: str = "https://api.tomtom.com/routing/matrix/2",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.cache_ttl_seconds = cache_ttl_seconds
        self.cache_max_entries = cache_max_entries
        self.max_distance_meters = max_distance_meters
        self.ride_hail_max_distance_meters = ride_hail_max_distance_meters
        self.tomtom_api_key = tomtom_api_key
        self.tomtom_base_url = tomtom_base_url.rstrip("/")
        self.tomtom_matrix_url = tomtom_matrix_url
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._cache: OrderedDict[
            tuple[Coordinate, Coordinate, str], tuple[float, PedestrianRoute]
        ] = OrderedDict()
        self._measure_cache: OrderedDict[
            tuple[Coordinate, Coordinate, str], tuple[float, PedestrianMeasure]
        ] = OrderedDict()
        self._client = client

    @property
    def enabled(self) -> bool:
        return bool(self.tomtom_api_key or self.base_url)

    def clear_cache(self) -> None:
        self._cache.clear()
        self._measure_cache.clear()

    async def measure_distances(
        self,
        start: Coordinate,
        targets: list[Coordinate],
        mode: TransportMode = TransportMode.WALK,
    ) -> list[PedestrianMeasure]:
        """Measure candidate access over the appropriate street network in one matrix call."""
        if not targets:
            return []
        keys = [(_rounded(start), _rounded(target), mode.value) for target in targets]
        results: list[PedestrianMeasure | None] = [None] * len(targets)
        missing: list[tuple[int, Coordinate]] = []
        for index, (key, target) in enumerate(zip(keys, targets, strict=True)):
            cached = self._get_measure_cached(key)
            if cached is None:
                missing.append((index, target))
            else:
                results[index] = cached
        if missing and (self.tomtom_api_key or self.base_url):
            try:
                for offset in range(0, len(missing), 40):
                    chunk = missing[offset : offset + 40]
                    measured = await self._request_access_matrix(
                        start, [target for _, target in chunk], mode
                    )
                    for (index, _), measure in zip(chunk, measured, strict=True):
                        results[index] = measure
                        self._put_measure_cached(keys[index], measure)
            except (TimeoutError, httpx.HTTPError, KeyError, TypeError, ValueError, IndexError):
                logger.warning("Pedestrian matrix unavailable; using conservative estimates")
        for index, target in enumerate(targets):
            if results[index] is None:
                distance = _air_distance_meters(start, target) * 1.25
                speed_meters_per_minute = 75 if mode is TransportMode.WALK else 25_000 / 60
                results[index] = PedestrianMeasure(
                    distance / speed_meters_per_minute, distance, routed=False
                )
        return [result for result in results if result is not None]

    async def enrich_segment(self, segment: Segment) -> Segment:
        if not self.enabled or segment.mode not in {
            TransportMode.WALK,
            TransportMode.RIDE_HAIL,
        }:
            return segment
        start = segment.coordinates[0]
        end = segment.coordinates[-1]
        key = (_rounded(start), _rounded(end), segment.mode.value)
        cached = self._get_cached(key)
        if cached is not None:
            return _apply_route(segment, cached)

        try:
            async with self._semaphore:
                cached = self._get_cached(key)
                if cached is None:
                    cached = await self._request_route(start, end, segment.mode)
                    self._put_cached(key, cached)
            return _apply_route(segment, cached)
        except (TimeoutError, httpx.HTTPError, KeyError, TypeError, ValueError, IndexError):
            # Deliberately omit coordinates and request bodies from logs.
            logger.warning("Pedestrian routing unavailable; retaining fallback geometry")
            return segment

    async def enrich_segments(self, segments: list[Segment]) -> list[Segment]:
        return list(await asyncio.gather(*(self.enrich_segment(segment) for segment in segments)))

    async def _request_route(
        self, start: Coordinate, end: Coordinate, mode: TransportMode
    ) -> PedestrianRoute:
        if self.tomtom_api_key:
            try:
                return await self._request_tomtom_route(start, end, mode)
            except (TimeoutError, httpx.HTTPError, KeyError, TypeError, ValueError, IndexError):
                if not self.base_url:
                    raise
                logger.warning("TomTom pedestrian routing unavailable; trying Valhalla")
        return await self._request_valhalla_route(start, end, mode)

    async def _request_valhalla_route(
        self, start: Coordinate, end: Coordinate, mode: TransportMode
    ) -> PedestrianRoute:
        payload = {
            "locations": [
                {"lat": start[1], "lon": start[0], "type": "break"},
                {"lat": end[1], "lon": end[0], "type": "break"},
            ],
            "costing": "pedestrian" if mode is TransportMode.WALK else "motor_scooter",
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
        maximum = (
            self.max_distance_meters
            if mode is TransportMode.WALK
            else self.ride_hail_max_distance_meters
        )
        if distance_meters > maximum:
            raise ValueError("Street route exceeded configured bound")
        return PedestrianRoute(
            coordinates, duration_min, distance_meters, WalkingRouteSource.VALHALLA
        )

    async def _request_tomtom_route(
        self, start: Coordinate, end: Coordinate, mode: TransportMode
    ) -> PedestrianRoute:
        path = f"{start[1]},{start[0]}:{end[1]},{end[0]}"
        params = {
            "key": self.tomtom_api_key,
            "travelMode": "pedestrian" if mode is TransportMode.WALK else "motorcycle",
            "routeRepresentation": "polyline",
            "computeTravelTimeFor": "all",
            "language": "id-ID",
        }
        if mode is TransportMode.RIDE_HAIL:
            # Traffic Flow is sampled separately so the selected base ETA is not
            # multiplied by current congestion twice.
            params["traffic"] = "false"
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
                (float(point["longitude"]), float(point["latitude"])) for point in leg["points"]
            ]
            coordinates.extend(decoded if not coordinates else decoded[1:])
        summary = route["summary"]
        distance_meters = float(summary["lengthInMeters"])
        duration_min = float(summary["travelTimeInSeconds"]) / 60
        if len(coordinates) < 2 or distance_meters <= 0 or duration_min <= 0:
            raise ValueError("Pedestrian route was empty")
        maximum = (
            self.max_distance_meters
            if mode is TransportMode.WALK
            else self.ride_hail_max_distance_meters
        )
        if distance_meters > maximum:
            raise ValueError("Street route exceeded configured bound")
        return PedestrianRoute(
            coordinates, duration_min, distance_meters, WalkingRouteSource.TOMTOM
        )

    async def _request_access_matrix(
        self,
        start: Coordinate,
        targets: list[Coordinate],
        mode: TransportMode,
    ) -> list[PedestrianMeasure]:
        if self.tomtom_api_key:
            try:
                return await self._request_tomtom_matrix(start, targets, mode)
            except (TimeoutError, httpx.HTTPError, KeyError, TypeError, ValueError, IndexError):
                if not self.base_url:
                    raise
                logger.warning("TomTom pedestrian matrix unavailable; trying Valhalla")
        return await self._request_valhalla_matrix(start, targets, mode)

    async def _request_valhalla_matrix(
        self,
        start: Coordinate,
        targets: list[Coordinate],
        mode: TransportMode,
    ) -> list[PedestrianMeasure]:
        payload = {
            "sources": [{"lat": start[1], "lon": start[0]}],
            "targets": [{"lat": target[1], "lon": target[0]} for target in targets],
            "costing": "pedestrian" if mode is TransportMode.WALK else "motor_scooter",
            "units": "kilometers",
        }
        if self._client is not None:
            response = await self._client.post(
                f"{self.base_url}/sources_to_targets",
                json=payload,
                timeout=self.timeout_seconds,
            )
        else:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/sources_to_targets",
                    json=payload,
                    timeout=self.timeout_seconds,
                )
        response.raise_for_status()
        cells = response.json()["sources_to_targets"][0]
        by_target = {int(cell["to_index"]): cell for cell in cells}
        return [
            PedestrianMeasure(
                duration_min=float(by_target[index]["time"]) / 60,
                distance_meters=float(by_target[index]["distance"]) * 1000,
            )
            for index in range(len(targets))
        ]

    async def _request_tomtom_matrix(
        self,
        start: Coordinate,
        targets: list[Coordinate],
        mode: TransportMode,
    ) -> list[PedestrianMeasure]:
        payload = {
            "origins": [{"point": {"latitude": start[1], "longitude": start[0]}}],
            "destinations": [
                {"point": {"latitude": target[1], "longitude": target[0]}} for target in targets
            ],
            "options": {
                "departAt": "any",
                "routeType": "fastest",
                "traffic": "historical",
                "travelMode": ("pedestrian" if mode is TransportMode.WALK else "motorcycle"),
            },
        }
        params = {"key": self.tomtom_api_key}
        if self._client is not None:
            response = await self._client.post(
                self.tomtom_matrix_url,
                params=params,
                json=payload,
                timeout=self.timeout_seconds,
            )
        else:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.tomtom_matrix_url,
                    params=params,
                    json=payload,
                    timeout=self.timeout_seconds,
                )
        response.raise_for_status()
        rows = response.json()["data"]
        by_target = {
            int(row["destinationIndex"]): row["routeSummary"]
            for row in rows
            if row.get("routeSummary")
        }
        return [
            PedestrianMeasure(
                duration_min=float(by_target[index]["travelTimeInSeconds"]) / 60,
                distance_meters=float(by_target[index]["lengthInMeters"]),
            )
            for index in range(len(targets))
        ]

    def _get_cached(self, key: tuple[Coordinate, Coordinate, str]) -> PedestrianRoute | None:
        entry = self._cache.get(key)
        if entry is None:
            return None
        stored_at, route = entry
        if monotonic() - stored_at >= self.cache_ttl_seconds:
            del self._cache[key]
            return None
        self._cache.move_to_end(key)
        return route

    def _put_cached(self, key: tuple[Coordinate, Coordinate, str], route: PedestrianRoute) -> None:
        self._cache[key] = (monotonic(), route)
        self._cache.move_to_end(key)
        while len(self._cache) > self.cache_max_entries:
            self._cache.popitem(last=False)

    def _get_measure_cached(
        self, key: tuple[Coordinate, Coordinate, str]
    ) -> PedestrianMeasure | None:
        entry = self._measure_cache.get(key)
        if entry is None:
            return None
        stored_at, measure = entry
        if monotonic() - stored_at >= self.cache_ttl_seconds:
            del self._measure_cache[key]
            return None
        self._measure_cache.move_to_end(key)
        return measure

    def _put_measure_cached(
        self,
        key: tuple[Coordinate, Coordinate, str],
        measure: PedestrianMeasure,
    ) -> None:
        self._measure_cache[key] = (monotonic(), measure)
        self._measure_cache.move_to_end(key)
        while len(self._measure_cache) > self.cache_max_entries:
            self._measure_cache.popitem(last=False)


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
        ride_hail_max_distance_meters=settings.ride_hail_router_max_distance_meters,
        tomtom_api_key=settings.effective_tomtom_api_key,
        tomtom_base_url=settings.tomtom_routing_url,
        tomtom_matrix_url=settings.tomtom_matrix_url,
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
    update = {
        "coordinates": route.coordinates,
        "avg_duration_min": round(max(0.1, route.duration_min), 1),
        "distance_meters": round(route.distance_meters),
    }
    if segment.mode is TransportMode.WALK:
        update.update(
            {
                "walking_distance_meters": round(route.distance_meters),
                "walking_route_source": route.source,
            }
        )
    return segment.model_copy(update=update)


def _rounded(coordinate: Coordinate) -> Coordinate:
    # About 0.1 m precision: stable cache keys without changing routed endpoints.
    return round(coordinate[0], 6), round(coordinate[1], 6)


def _air_distance_meters(first: Coordinate, second: Coordinate) -> float:
    from math import asin, cos, radians, sin, sqrt

    lng1, lat1 = first
    lng2, lat2 = second
    delta_lat = radians(lat2 - lat1)
    delta_lng = radians(lng2 - lng1)
    value = sin(delta_lat / 2) ** 2 + (
        cos(radians(lat1)) * cos(radians(lat2)) * sin(delta_lng / 2) ** 2
    )
    return 2 * 6_371_008.8 * asin(sqrt(value))
