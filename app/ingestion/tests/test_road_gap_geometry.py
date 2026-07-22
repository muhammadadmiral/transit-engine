import httpx
import pytest

from app.ingestion.geometry.road_gaps import RoadGapRepairer


def _encode_pair() -> str:
    encoded = ""
    lat = lng = 0
    for point in [(106.8, -6.2), (106.805, -6.201), (106.81, -6.2)]:
        d_lat = int(round(point[1] * 1_000_000)) - lat
        d_lng = int(round(point[0] * 1_000_000)) - lng
        lat += d_lat
        lng += d_lng
        for value in (d_lat, d_lng):
            value = ~(value << 1) if value < 0 else value << 1
            while value >= 0x20:
                encoded += chr((0x20 | (value & 0x1F)) + 63)
                value >>= 5
            encoded += chr(value + 63)
    return encoded


@pytest.mark.asyncio
async def test_repairs_bounded_gap_with_road_geometry() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "trip": {
                    "legs": [{"shape": _encode_pair()}],
                    "summary": {"length": 1.2},
                }
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    repairer = RoadGapRepairer("https://valhalla.test", client=client)
    result = await repairer.repair([(106.8, -6.2), (106.81, -6.2)])
    await client.aclose()

    assert result is not None
    assert result.repaired_gaps == 1
    assert len(result.coordinates) == 3


@pytest.mark.asyncio
async def test_rejects_gap_too_large_to_infer() -> None:
    repairer = RoadGapRepairer("https://valhalla.test")

    result = await repairer.repair([(106.8, -6.2), (106.9, -6.2)])

    assert result is None
