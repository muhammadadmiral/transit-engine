"""TomTom map matching for already sourced transit corridor traces."""

from math import ceil

import httpx

from app.core.config import Settings, get_settings
from app.routing.flexible import distance_meters

MAX_POINTS = 5000
MAX_GAP_METERS = 5900


class TomTomRoadSnapper:
    """Snap a trace to roads while rejecting implausible provider responses."""

    def __init__(
        self,
        settings: Settings | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.client = client

    @property
    def enabled(self) -> bool:
        return bool(self.settings.effective_tomtom_api_key)

    async def snap(
        self, coordinates: list[tuple[float, float]]
    ) -> list[tuple[float, float]] | None:
        if not self.enabled or len(coordinates) < 2:
            return None
        trace = _limit_points(coordinates)
        pairs = zip(trace, trace[1:], strict=False)
        if any(_distance(first, second) > MAX_GAP_METERS for first, second in pairs):
            return None
        payload = {
            "points": [
                {
                    "geometry": {"coordinates": [lng, lat], "type": "Point"},
                    "properties": {},
                    "type": "Feature",
                }
                for lng, lat in trace
            ]
        }
        params = {
            "fields": "{route{type,geometry{type,coordinates}}}",
            "key": self.settings.effective_tomtom_api_key,
            "measurementSystem": "metric",
            # Taxi follows ordinary passenger-road access and works better for
            # small angkot than Bus restrictions on incomplete local roads.
            "vehicleType": "Taxi",
        }
        try:
            response = await self._post(params, payload)
            response.raise_for_status()
            raw = response.json().get("route", {}).get("geometry", {}).get("coordinates", [])
            snapped = [(float(point[0]), float(point[1])) for point in raw if len(point) >= 2]
        except (httpx.HTTPError, TypeError, ValueError):
            return None
        return snapped if _plausible(coordinates, snapped) else None

    async def _post(self, params: dict[str, str], payload: dict) -> httpx.Response:
        if self.client is not None:
            return await self.client.post(
                self.settings.tomtom_snap_to_roads_url, params=params, json=payload
            )
        async with httpx.AsyncClient(timeout=45) as client:
            return await client.post(
                self.settings.tomtom_snap_to_roads_url, params=params, json=payload
            )


def _limit_points(coordinates: list[tuple[float, float]]) -> list[tuple[float, float]]:
    if len(coordinates) <= MAX_POINTS:
        return coordinates
    step = ceil((len(coordinates) - 1) / (MAX_POINTS - 1))
    reduced = coordinates[::step]
    if reduced[-1] != coordinates[-1]:
        reduced.append(coordinates[-1])
    return reduced


def _plausible(
    original: list[tuple[float, float]], snapped: list[tuple[float, float]]
) -> bool:
    if len(snapped) < 2:
        return False
    if _distance(original[0], snapped[0]) > 180 or _distance(original[-1], snapped[-1]) > 180:
        return False
    original_length = _length(original)
    snapped_length = _length(snapped)
    return original_length > 0 and 0.65 <= snapped_length / original_length <= 1.55


def _length(coordinates: list[tuple[float, float]]) -> float:
    pairs = zip(coordinates, coordinates[1:], strict=False)
    return sum(_distance(first, second) for first, second in pairs)


def _distance(first: tuple[float, float], second: tuple[float, float]) -> float:
    return distance_meters(first[1], first[0], second[1], second[0])
