import pytest
from httpx import ASGITransport, AsyncClient

from app.geocoding.service import get_geocoding_service
from app.main import app
from app.models.schema import GeocodeSource, PlaceResult


class FakeGeocoder:
    async def search(self, query: str, limit: int) -> list[PlaceResult]:
        assert query == "lokasi uji depok"
        assert limit == 6
        return [
            PlaceResult(
                area="Depok",
                category="university",
                id="osm:way:401977089",
                label="Lokasi Uji Depok",
                lat=-6.3539705,
                lng=106.8412175,
                subtitle="Jalan Akses UI, Depok",
                source=GeocodeSource.NOMINATIM,
            )
        ]

    async def reverse(self, lat: float, lng: float) -> PlaceResult:
        return PlaceResult(
            area="Depok",
            category="university",
            id="osm:way:401977089",
            label="Lokasi Uji Depok",
            lat=lat,
            lng=lng,
            subtitle="Jalan Akses UI, Depok",
            source=GeocodeSource.NOMINATIM,
        )


@pytest.mark.asyncio
async def test_backend_owns_search_and_reverse_geocode_contract() -> None:
    app.dependency_overrides[get_geocoding_service] = FakeGeocoder
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            search = await client.get("/geocode/search", params={"q": "lokasi uji depok"})
            reverse = await client.get(
                "/geocode/reverse", params={"lat": -6.3539705, "lng": 106.8412175}
            )
    finally:
        app.dependency_overrides.clear()

    assert search.status_code == 200
    assert search.json()[0]["label"] == "Lokasi Uji Depok"
    assert search.json()[0]["source"] == "nominatim"
    assert reverse.status_code == 200
    assert reverse.json()["area"] == "Depok"
