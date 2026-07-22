from collections.abc import AsyncIterator
from datetime import date

import pytest
from httpx import ASGITransport, AsyncClient

from app.db.session import get_session
from app.main import app
from app.models.schema import (
    DataConfidence,
    NearbyStop,
    NearbyStopPurpose,
    Segment,
    ServiceCategory,
    TransportMode,
)
from app.routers import route_search as route_search_router
from app.routing.graph import build_graph
from app.routing.schedules import ServiceFrequencyIndex


async def fake_session() -> AsyncIterator[object]:
    yield object()


def ride_segment() -> Segment:
    return Segment(
        id="ride",
        route_id="transjakarta:JAK.44:0",
        route_code="JAK.44",
        route_name="Andara - Stasiun Universitas Pancasila",
        from_stop_id="origin-stop",
        to_stop_id="destination-stop",
        mode=TransportMode.TRANSJAKARTA,
        service_category=ServiceCategory.MICROTRANS,
        service_name="Mikrotrans",
        avg_duration_min=12,
        fare=0,
        fare_product_id="transjakarta:regular",
        data_confidence=DataConfidence.OFFICIAL,
        last_verified_at=date(2026, 7, 21),
        color="009999",
        coordinates=[(106.8, -6.3), (106.82, -6.32)],
    )


@pytest.mark.asyncio
async def test_coordinate_route_search_chooses_candidates_in_backend(monkeypatch) -> None:
    calls: list[NearbyStopPurpose] = []

    async def nearby(session: object, **kwargs: object) -> list[NearbyStop]:
        purpose = kwargs["purpose"]
        assert isinstance(purpose, NearbyStopPurpose)
        assert kwargs["limit"] == 64
        calls.append(purpose)
        is_origin = purpose is NearbyStopPurpose.ORIGIN
        return [
            NearbyStop(
                id="origin-stop" if is_origin else "destination-stop",
                name="Origin" if is_origin else "Destination",
                lat=-6.3 if is_origin else -6.32,
                lng=106.8 if is_origin else 106.82,
                modes=[TransportMode.TRANSJAKARTA],
                distance_meters=150,
                can_board=is_origin,
                can_alight=not is_origin,
            )
        ]

    async def graph(session: object):
        return build_graph([ride_segment()])

    async def schedules(session: object):
        return ServiceFrequencyIndex([])

    monkeypatch.setattr(route_search_router, "find_nearby_stops", nearby)
    monkeypatch.setattr(route_search_router, "get_routing_graph", graph)
    monkeypatch.setattr(route_search_router, "get_schedule_index", schedules)
    app.dependency_overrides[get_session] = fake_session
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/route-search",
                json={
                    "originLat": -6.299,
                    "originLng": 106.799,
                    "destinationLat": -6.321,
                    "destinationLng": 106.821,
                    "maxTransfers": 1,
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert calls == [NearbyStopPurpose.ORIGIN, NearbyStopPurpose.DESTINATION]
    body = response.json()
    assert body["originStopId"] == "coordinate:origin"
    assert body["destinationStopId"] == "coordinate:destination"
    assert [segment["mode"] for segment in body["options"][0]["segments"]] == [
        "walk",
        "transjakarta",
        "walk",
    ]
    assert body["options"][0]["segments"][1]["routeCode"] == "JAK.44"
    # Fake session can't query the stops table; segments keep their raw IDs.
    ride = body["options"][0]["segments"][1]
    assert ride["fromStopId"] == "origin-stop"
    assert ride["toStopId"] == "destination-stop"


@pytest.mark.asyncio
async def test_route_search_rejects_mixed_stop_and_coordinate_endpoint() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/route-search",
            json={
                "originStopId": "origin-stop",
                "originLat": -6.3,
                "originLng": 106.8,
                "destinationStopId": "destination-stop",
            },
        )

    assert response.status_code == 422
