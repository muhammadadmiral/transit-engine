from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import pytest

from app.core.config import Settings
from app.models.schema import WeatherSource
from app.routing.tests.test_pedestrian_router import _walk_segment
from app.routing.weather import WeatherEstimator


@pytest.mark.asyncio
async def test_open_meteo_rain_adjusts_walking_eta_and_exposes_source() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "current": {
                    "time": "2026-07-22T11:00",
                    "precipitation": 3.0,
                    "weather_code": 63,
                }
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    estimator = WeatherEstimator(Settings(), client)
    segment = _walk_segment()
    segment.avg_duration_min = 10

    result = await estimator.enrich_segments([segment], datetime.now(ZoneInfo("Asia/Jakarta")))
    await client.aclose()

    assert result[0].avg_duration_min == 12.5
    assert result[0].weather_source is WeatherSource.OPEN_METEO
    assert result[0].precipitation_mm == 3.0
