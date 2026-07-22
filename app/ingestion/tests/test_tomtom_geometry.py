import httpx
import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.ingestion.geometry.tomtom import TomTomRoadSnapper


@pytest.mark.asyncio
async def test_snapper_accepts_plausible_road_geometry() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["vehicleType"] == "Taxi"
        assert "secret" not in str(request.content)
        return httpx.Response(
            200,
            json={
                "route": {
                    "geometry": {
                        "coordinates": [
                            [106.80001, -6.20001],
                            [106.805, -6.205],
                            [106.81001, -6.21001],
                        ]
                    }
                }
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    snapper = TomTomRoadSnapper(Settings(tomtom_api_key=SecretStr("secret")), client)
    result = await snapper.snap([(106.8, -6.2), (106.81, -6.21)])
    await client.aclose()

    assert result is not None
    assert len(result) == 3


@pytest.mark.asyncio
async def test_snapper_rejects_geometry_with_shifted_endpoints() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "route": {
                    "geometry": {
                        "coordinates": [[107.0, -6.4], [107.01, -6.41]]
                    }
                }
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    snapper = TomTomRoadSnapper(Settings(tomtom_api_key=SecretStr("secret")), client)
    result = await snapper.snap([(106.8, -6.2), (106.81, -6.21)])
    await client.aclose()

    assert result is None
