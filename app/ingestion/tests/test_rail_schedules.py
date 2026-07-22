from datetime import datetime

from app.ingestion.curated.rail_schedules import _fixed_operator_frequencies
from app.models.schema import (
    DataConfidence,
    Segment,
    ServiceCategory,
    TransportMode,
)
from app.routing.schedules import ServiceFrequencyIndex, apply_scheduled_waits


def rail_segment(route_id: str, mode: TransportMode) -> Segment:
    return Segment(
        id="rail",
        route_id=route_id,
        from_stop_id="a",
        to_stop_id="b",
        mode=mode,
        service_category=ServiceCategory.MAIN,
        service_name="Rail",
        avg_duration_min=12,
        fare=5000,
        data_confidence=DataConfidence.OFFICIAL,
        last_verified_at=datetime(2026, 7, 22).date(),
        color="123456",
        coordinates=[(106.8, -6.2), (106.81, -6.21)],
    )


def test_mrt_wait_uses_official_peak_and_offpeak_headway() -> None:
    index = ServiceFrequencyIndex(_fixed_operator_frequencies())
    segment = rail_segment("mrt:north-south", TransportMode.MRT)

    peak, source = index.expected_wait(segment, datetime(2026, 7, 22, 8, 0))
    offpeak, _ = index.expected_wait(segment, datetime(2026, 7, 22, 11, 0))

    assert peak == 2.5
    assert offpeak == 5
    assert source and "jakartamrt.co.id" in source


def test_wait_is_added_once_per_boarding_not_each_rail_edge() -> None:
    index = ServiceFrequencyIndex(_fixed_operator_frequencies())
    first = rail_segment("mrt:north-south", TransportMode.MRT)
    second = first.model_copy(update={"id": "rail-2", "from_stop_id": "b", "to_stop_id": "c"})

    result = apply_scheduled_waits([first, second], index, datetime(2026, 7, 22, 8, 0))

    assert [segment.scheduled_wait_min for segment in result] == [2.5, 0]
