"""Focused coverage for the Valhalla-compatible pedestrian adapter."""

from __future__ import annotations

import asyncio
from datetime import date
from types import SimpleNamespace

import httpx
import pytest

from app.models.schema import (
    DataConfidence,
    Segment,
    ServiceCategory,
    TransportMode,
    WalkingRouteSource,
)
from app.routing import pedestrian
from app.routing.pedestrian import PedestrianRouter, get_pedestrian_router


def _walk_segment(*, start: tuple[float, float] = (106.8, -6.2)) -> Segment:
    end = (start[0] + 0.001, start[1] + 0.001)
    return Segment(
        id=f"walk:{start[0]}:{start[1]}",
        route_id="walk",
        route_code="WALK",
        route_name="Walking transfer",
        from_stop_id="a",
        to_stop_id="b",
        mode=TransportMode.WALK,
        service_category=ServiceCategory.MAIN,
        service_name="walk",
        avg_duration_min=1.0,
        fare=0,
        data_confidence=DataConfidence.OFFICIAL,
        last_verified_at=date(2026, 7, 22),
        color="888888",
        coordinates=[start, end],
    )


def _ride_segment() -> Segment:
    return Segment(
        id="ride",
        route_id="transjakarta:JAK.44:0",
        route_code="JAK.44",
        route_name="Andara - Universitas Pancasila",
        from_stop_id="a",
        to_stop_id="b",
        mode=TransportMode.TRANSJAKARTA,
        service_category=ServiceCategory.MICROTRANS,
        service_name="Mikrotrans",
        avg_duration_min=12,
        fare=0,
        data_confidence=DataConfidence.OFFICIAL,
        last_verified_at=date(2026, 7, 21),
        color="009999",
        coordinates=[(106.8, -6.3), (106.81, -6.31)],
    )


def _valhalla_response() -> dict[str, object]:
    encoded = pedestrian.decode_polyline6.__name__ and _encode_pair()
    return {
        "trip": {
            "legs": [{"shape": encoded, "summary": {}}],
            "summary": {"length": 0.42, "time": 360.0},
        }
    }


def _encode_pair() -> str:
    # Valhalla precision-six polyline for [(106.8, -6.2), (106.801, -6.201)].
    encoded = ""
    lat = lng = 0
    for point in [(106.8, -6.2), (106.801, -6.201)]:
        d_lat = int(round(point[1] * 1_000_000)) - lat
        d_lng = int(round(point[0] * 1_000_000)) - lng
        lat += d_lat
        lng += d_lng
        for value in (d_lat, d_lng):
            value = ~(value << 1) if value < 0 else value << 1
            while True:
                chunk = value & 0x1F
                if chunk >= 0x20:
                    encoded += chr(chunk + 63)
                    value >>= 5
                else:
                    encoded += chr(chunk + 63)
                    break
    return encoded


def _mock_client(responses: list[dict[str, object] | Exception]) -> httpx.AsyncClient:
    calls = SimpleNamespace(count=0)
    queue = list(reversed(responses))

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.count += 1
        payload = queue.pop()
        if isinstance(payload, Exception):
            raise payload
        return httpx.Response(200, json=payload)

    transport = httpx.MockTransport(handler)
    return httpx.AsyncClient(transport=transport), calls


@pytest.mark.asyncio
async def test_disabled_router_returns_unchanged_segment() -> None:
    router = PedestrianRouter(base_url="")
    segment = _walk_segment()
    enriched = await router.enrich_segment(segment)
    assert enriched is segment


@pytest.mark.asyncio
async def test_non_walking_segment_passes_through() -> None:
    router = PedestrianRouter(base_url="http://valhalla")
    segment = _ride_segment()
    enriched = await router.enrich_segment(segment)
    assert enriched is segment


@pytest.mark.asyncio
async def test_successful_call_replaces_geometry_with_metadata() -> None:
    client, _ = _mock_client([_valhalla_response()])
    router = PedestrianRouter(base_url="http://valhalla", client=client)
    enriched = await router.enrich_segment(_walk_segment())
    assert enriched.walking_route_source is WalkingRouteSource.VALHALLA
    assert enriched.walking_distance_meters == pytest.approx(420, abs=5)
    assert enriched.avg_duration_min == 6.0
    assert len(enriched.coordinates) >= 2
    # No raw coordinates logged: assert we did not raise and segment kept an ID.
    assert enriched.id.startswith("walk:")


@pytest.mark.asyncio
async def test_falls_back_when_remote_returns_error() -> None:
    client, _ = _mock_client([httpx.ConnectError("kaboom", request=httpx.Request("POST", "/"))])
    router = PedestrianRouter(base_url="http://valhalla", client=client)
    segment = _walk_segment()
    enriched = await router.enrich_segment(segment)
    assert enriched is segment
    assert enriched.walking_route_source is None


@pytest.mark.asyncio
async def test_cache_returns_same_route_for_repeated_request() -> None:
    client, calls = _mock_client([_valhalla_response()])
    router = PedestrianRouter(base_url="http://valhalla", client=client)
    first = await router.enrich_segment(_walk_segment())
    second = await router.enrich_segment(_walk_segment())
    assert calls.count == 1
    assert first.coordinates == second.coordinates


@pytest.mark.asyncio
async def test_distance_above_bound_returns_fallback() -> None:
    payload = _valhalla_response()
    payload["trip"]["summary"]["length"] = 99.0  # 99 km
    client, _ = _mock_client([payload])
    router = PedestrianRouter(
        base_url="http://valhalla",
        client=client,
        max_distance_meters=5000,
    )
    segment = _walk_segment()
    enriched = await router.enrich_segment(segment)
    assert enriched is segment


@pytest.mark.asyncio
async def test_concurrency_is_bounded_by_semaphore() -> None:
    in_flight = 0
    peak = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0.05)
        in_flight -= 1
        return httpx.Response(200, json=_valhalla_response())

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    router = PedestrianRouter(base_url="http://valhalla", client=client, max_concurrency=2)

    segments = [_walk_segment(start=(106.8 + 0.0001 * i, -6.2 - 0.0001 * i)) for i in range(6)]
    await router.enrich_segments(segments)
    assert peak <= 2


def test_get_pedestrian_router_is_cached() -> None:
    pedestrian.get_pedestrian_router.cache_clear()
    first = get_pedestrian_router()
    second = get_pedestrian_router()
    assert first is second


def test_invalidate_pedestrian_cache_clears_singleton() -> None:
    pedestrian.get_pedestrian_router.cache_clear()
    router = get_pedestrian_router()
    router._cache[((0.0, 0.0), (0.0, 0.0))] = (
        0.0,
        pedestrian.PedestrianRoute([(0.0, 0.0), (1.0, 1.0)], 1.0, 1.0),
    )
    pedestrian.invalidate_pedestrian_cache()
    assert router._cache == {}
