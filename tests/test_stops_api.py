from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from app.db.session import get_session
from app.main import app
from app.models.schema import NearbyStop, NearbyStopPurpose, Stop, TransportMode
from app.routers import stops as stops_router


async def fake_session() -> AsyncIterator[object]:
    yield object()


@pytest.mark.asyncio
async def test_searches_stops_for_autocomplete(monkeypatch) -> None:
    async def fake_search_stops(session: object, query: str, limit: int) -> list[Stop]:
        assert query == "Monas"
        assert limit == 5
        return [
            Stop(
                id="transjakarta:monas",
                name="Monas",
                lat=-6.1754,
                lng=106.8272,
                modes=[TransportMode.TRANSJAKARTA],
            )
        ]

    monkeypatch.setattr(stops_router, "search_stops", fake_search_stops)
    app.dependency_overrides[get_session] = fake_session
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/stops", params={"q": "Monas", "limit": 5})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": "transjakarta:monas",
            "name": "Monas",
            "lat": -6.1754,
            "lng": 106.8272,
            "modes": ["transjakarta"],
        }
    ]


@pytest.mark.asyncio
async def test_rejects_an_autocomplete_query_shorter_than_two_characters() -> None:
    app.dependency_overrides[get_session] = fake_session
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/stops", params={"q": "M"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_finds_directionally_usable_nearby_stops(monkeypatch) -> None:
    async def fake_find_nearby_stops(
        session: object,
        *,
        lat: float,
        lng: float,
        radius_meters: int,
        limit: int,
        mode: TransportMode | None,
        purpose: NearbyStopPurpose,
    ) -> list[NearbyStop]:
        assert (lat, lng) == (-6.3605, 106.8318)
        assert radius_meters == 750
        assert limit == 5
        assert mode is TransportMode.BIKUN
        assert purpose is NearbyStopPurpose.ORIGIN
        return [
            NearbyStop(
                id="bikun:stasiun-ui",
                name="Halte Stasiun UI",
                lat=-6.360531,
                lng=106.831775,
                modes=[TransportMode.BIKUN],
                distance_meters=4.3,
                can_board=True,
                can_alight=True,
            )
        ]

    monkeypatch.setattr(stops_router, "find_nearby_stops", fake_find_nearby_stops)
    app.dependency_overrides[get_session] = fake_session
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(
                "/stops/nearby",
                params={
                    "lat": -6.3605,
                    "lng": 106.8318,
                    "radiusMeters": 750,
                    "limit": 5,
                    "mode": "bikun",
                    "purpose": "origin",
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": "bikun:stasiun-ui",
            "name": "Halte Stasiun UI",
            "lat": -6.360531,
            "lng": 106.831775,
            "modes": ["bikun"],
            "distanceMeters": 4.3,
            "canBoard": True,
            "canAlight": True,
        }
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "params",
    [
        {"lat": 91, "lng": 106.8},
        {"lat": -6.2, "lng": 181},
        {"lat": -6.2, "lng": 106.8, "radiusMeters": 49},
        {"lat": -6.2, "lng": 106.8, "radiusMeters": 5001},
        {"lat": -6.2, "lng": 106.8, "purpose": "boarding-ish"},
    ],
)
async def test_rejects_invalid_nearby_stop_parameters(params: dict[str, object]) -> None:
    app.dependency_overrides[get_session] = fake_session
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/stops/nearby", params=params)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_nearby_stop_dns_failure_is_reported_as_service_unavailable(monkeypatch) -> None:
    async def unavailable(*args: object, **kwargs: object) -> list[NearbyStop]:
        raise OSError("temporary DNS failure")

    monkeypatch.setattr(stops_router, "find_nearby_stops", unavailable)
    app.dependency_overrides[get_session] = fake_session
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(
                "/stops/nearby",
                params={"lat": -6.2, "lng": 106.8},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json() == {"detail": "Nearby transit stops are temporarily unavailable"}
