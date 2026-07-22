from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.models.schema import (
    DataConfidence,
    Segment,
    ServiceCategory,
    TrafficSource,
    TransportMode,
)
from app.routing.traffic import RoadTrafficEstimator, historical_traffic_factor


def _segment(mode: TransportMode = TransportMode.ANGKOT) -> Segment:
    return Segment(
        id="road",
        route_id="road",
        from_stop_id="a",
        to_stop_id="b",
        mode=mode,
        service_category=ServiceCategory.FEEDER,
        service_name="Road service",
        avg_duration_min=10,
        fare=5000,
        data_confidence=DataConfidence.OFFICIAL,
        last_verified_at=datetime(2026, 7, 22).date(),
        color="22A447",
        coordinates=[(106.8, -6.2), (106.81, -6.21)],
    )


def test_historical_profile_affects_only_road_modes() -> None:
    peak = datetime(2026, 7, 22, 8, tzinfo=ZoneInfo("Asia/Jakarta"))
    assert historical_traffic_factor(_segment(), peak) == 1.4
    assert historical_traffic_factor(_segment(TransportMode.KRL), peak) == 1.0


@pytest.mark.asyncio
async def test_live_tomtom_factor_is_applied_and_labeled() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "flowSegmentData": {
                    "currentTravelTime": 180,
                    "freeFlowTravelTime": 100,
                    "confidence": 0.9,
                }
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    settings = Settings(tomtom_traffic_api_key=SecretStr("test"))
    estimator = RoadTrafficEstimator(settings, client)
    result = await estimator.enrich_segments([_segment()], datetime.now(ZoneInfo("Asia/Jakarta")))
    await client.aclose()

    assert result[0].avg_duration_min == 18
    assert result[0].traffic_factor == 1.8
    assert result[0].traffic_source is TrafficSource.LIVE_TOMTOM


@pytest.mark.asyncio
async def test_historical_fallback_is_explicit_without_key() -> None:
    estimator = RoadTrafficEstimator(Settings(tomtom_traffic_api_key=SecretStr("")))
    result = await estimator.enrich_segments(
        [_segment()], datetime(2026, 7, 22, 8, tzinfo=ZoneInfo("Asia/Jakarta"))
    )

    assert result[0].avg_duration_min == 14
    assert result[0].traffic_source is TrafficSource.HISTORICAL_PROFILE
