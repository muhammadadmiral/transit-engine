from datetime import date
from unittest.mock import AsyncMock

import pytest

from app.models.schema import DataConfidence, Segment, TransportMode
from app.routing import graph_cache


@pytest.mark.asyncio
async def test_reuses_graph_until_invalidated(monkeypatch) -> None:
    segment = Segment(
        id="segment",
        route_id="route",
        from_stop_id="a",
        to_stop_id="b",
        mode=TransportMode.TRANSJAKARTA,
        avg_duration_min=3,
        fare=3500,
        data_confidence=DataConfidence.OFFICIAL,
        last_verified_at=date(2026, 7, 20),
        color="009999",
        coordinates=[(106.8, -6.2), (106.81, -6.21)],
    )
    load_segments = AsyncMock(return_value=[segment])
    monkeypatch.setattr(graph_cache, "load_segments", load_segments)
    graph_cache.invalidate_graph_cache()

    first = await graph_cache.get_routing_graph(object())
    second = await graph_cache.get_routing_graph(object())

    assert first is second
    assert load_segments.await_count == 1

    graph_cache.invalidate_graph_cache()
    await graph_cache.get_routing_graph(object())
    assert load_segments.await_count == 2
