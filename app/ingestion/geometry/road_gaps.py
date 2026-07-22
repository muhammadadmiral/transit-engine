"""Repair short gaps in sourced corridor traces through an OSM road router."""

import asyncio
from dataclasses import dataclass

import httpx

from app.routing.pedestrian import decode_polyline6

Coordinate = tuple[float, float]


@dataclass(frozen=True)
class GapRepairResult:
    coordinates: list[Coordinate]
    repaired_gaps: int


class RoadGapRepairer:
    """Fill bounded trace gaps without inventing a route between termini."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float = 12,
        min_gap_meters: float = 350,
        max_gap_meters: float = 1500,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.min_gap_meters = min_gap_meters
        self.max_gap_meters = max_gap_meters
        self.client = client

    async def repair(self, coordinates: list[Coordinate]) -> GapRepairResult | None:
        if len(coordinates) < 2:
            return None
        result = [coordinates[0]]
        repaired = 0
        for start, end in zip(coordinates, coordinates[1:], strict=False):
            gap = _distance_meters(start, end)
            if gap <= self.min_gap_meters:
                result.append(end)
                continue
            if gap > self.max_gap_meters:
                return None
            routed = await self._route(start, end)
            if routed is None:
                return None
            result.extend(routed[1:])
            repaired += 1
            await asyncio.sleep(0.15)
        return GapRepairResult(result, repaired)

    async def _route(self, start: Coordinate, end: Coordinate) -> list[Coordinate] | None:
        payload = {
            "locations": [
                {"lat": start[1], "lon": start[0], "type": "break"},
                {"lat": end[1], "lon": end[0], "type": "break"},
            ],
            "costing": "auto",
            "units": "kilometers",
        }
        try:
            if self.client is not None:
                response = await self.client.post(
                    f"{self.base_url}/route",
                    json=payload,
                    timeout=self.timeout_seconds,
                )
            else:
                async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                    response = await client.post(f"{self.base_url}/route", json=payload)
            response.raise_for_status()
            trip = response.json()["trip"]
            routed: list[Coordinate] = []
            for leg in trip["legs"]:
                decoded = decode_polyline6(leg["shape"])
                routed.extend(decoded if not routed else decoded[1:])
            length_meters = float(trip["summary"]["length"]) * 1000
        except (httpx.HTTPError, KeyError, TypeError, ValueError, IndexError):
            return None
        direct = _distance_meters(start, end)
        if (
            len(routed) < 2
            or _distance_meters(start, routed[0]) > 120
            or _distance_meters(end, routed[-1]) > 120
            or length_meters > max(600, direct * 3.5)
        ):
            return None
        routed[0] = start
        routed[-1] = end
        return routed


def _distance_meters(first: Coordinate, second: Coordinate) -> float:
    # Equirectangular distance is only a guardrail for sub-1.5 km trace gaps;
    # route geometry and distance come from the provider.
    from math import cos, hypot, radians

    mean_latitude = radians((first[1] + second[1]) / 2)
    return hypot(
        (first[0] - second[0]) * 111_320 * cos(mean_latitude),
        (first[1] - second[1]) * 110_574,
    )
