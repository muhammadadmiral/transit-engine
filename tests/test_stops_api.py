from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from app.db.session import get_session
from app.main import app
from app.models.schema import Stop, TransportMode
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
