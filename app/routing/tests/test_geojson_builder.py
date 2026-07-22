from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.models.schema import (
    DataConfidence,
    Segment,
    ServiceCategory,
    TrafficSource,
    TransportMode,
)
from app.routing.geojson_builder import build_feature_collection


def test_geojson_exposes_eta_provenance() -> None:
    updated = datetime(2026, 7, 22, 12, tzinfo=ZoneInfo("Asia/Jakarta"))
    segment = Segment(
        id="angkot:edge",
        route_id="angkot:test",
        from_stop_id="a",
        to_stop_id="b",
        mode=TransportMode.ANGKOT,
        service_category=ServiceCategory.FEEDER,
        service_name="Angkot test",
        avg_duration_min=12,
        fare=5000,
        data_confidence=DataConfidence.COMMUNITY,
        last_verified_at=date(2026, 7, 22),
        color="22A447",
        coordinates=[(106.8, -6.2), (106.81, -6.21)],
        traffic_factor=1.4,
        traffic_source=TrafficSource.LIVE_TOMTOM,
        traffic_updated_at=updated,
    )

    properties = build_feature_collection([segment]).features[0].properties

    assert properties["trafficFactor"] == 1.4
    assert properties["trafficSource"] == "live_tomtom"
    assert properties["trafficUpdatedAt"] == updated.isoformat()
