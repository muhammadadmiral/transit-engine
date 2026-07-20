from app.fares.catalog import DEFAULT_FARE_CATALOG
from app.fares.engine import quote_journey
from app.ingestion.curated.rail import build_rail_dataset
from app.models.schema import FareStatus, TransportMode


def test_builds_only_currently_operational_mrt_and_lrt_jakarta_stations() -> None:
    dataset = build_rail_dataset()

    assert len(dataset.stops) == 19
    assert len(dataset.segments) == 34
    assert {stop.modes[0] for stop in dataset.stops} == {
        TransportMode.MRT,
        TransportMode.LRT,
    }
    assert not any("manggarai" in stop.id for stop in dataset.stops)


def test_quotes_mrt_fare_from_official_od_matrix() -> None:
    dataset = build_rail_dataset()
    northbound = {
        segment.from_stop_id: segment
        for segment in dataset.segments
        if segment.mode is TransportMode.MRT and segment.to_stop_id != "mrt:lebak-bulus"
    }
    ride = []
    current = "mrt:lebak-bulus"
    while current != "mrt:bundaran-hi":
        segment = northbound[current]
        ride.append(segment)
        current = segment.to_stop_id

    quote = quote_journey(ride, catalog=DEFAULT_FARE_CATALOG)

    assert quote.status is FareStatus.EXACT
    assert quote.estimated_amount == 14000
