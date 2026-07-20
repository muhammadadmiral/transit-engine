from app.fares.catalog import DEFAULT_FARE_CATALOG
from app.fares.engine import quote_journey
from app.ingestion.curated.bikun import build_bikun_dataset
from app.ingestion.curated.krl import BOGOR_MAIN, build_krl_dataset
from app.ingestion.curated.rail import build_rail_dataset
from app.models.schema import FareStatus, TransportMode


def test_builds_only_currently_operational_mrt_and_lrt_jakarta_stations() -> None:
    dataset = build_rail_dataset()

    assert len(dataset.stops) == 37
    assert len(dataset.segments) == 82
    assert {stop.modes[0] for stop in dataset.stops} == {
        TransportMode.MRT,
        TransportMode.LRT,
    }
    assert not any("manggarai" in stop.id for stop in dataset.stops)
    assert all(len(segment.coordinates) > 2 for segment in dataset.segments)
    stops = {stop.id: stop for stop in dataset.stops}
    assert all(
        segment.coordinates[0] == (stops[segment.from_stop_id].lng, stops[segment.from_stop_id].lat)
        and segment.coordinates[-1]
        == (stops[segment.to_stop_id].lng, stops[segment.to_stop_id].lat)
        for segment in dataset.segments
    )


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


def test_builds_complete_krl_jabodetabek_topology() -> None:
    dataset = build_krl_dataset()

    assert len(dataset.stops) == 82
    assert len(dataset.segments) == 166
    assert {stop.modes[0] for stop in dataset.stops} == {TransportMode.KRL}
    assert {segment.route_id for segment in dataset.segments} == {
        "krl:bogor-line",
        "krl:cikarang-loop-line",
        "krl:rangkasbitung-line",
        "krl:tangerang-line",
        "krl:tanjung-priok-line",
    }
    assert {"krl:jatake", "krl:nambo", "krl:rangkasbitung"} <= {stop.id for stop in dataset.stops}
    assert all(len(segment.coordinates) > 2 for segment in dataset.segments)
    stops = {stop.id: stop for stop in dataset.stops}
    assert all(
        segment.coordinates[0] == (stops[segment.from_stop_id].lng, stops[segment.from_stop_id].lat)
        and segment.coordinates[-1]
        == (stops[segment.to_stop_id].lng, stops[segment.to_stop_id].lat)
        for segment in dataset.segments
    )


def test_quotes_krl_distance_band_as_estimate() -> None:
    dataset = build_krl_dataset()
    by_pair = {(segment.from_stop_id, segment.to_stop_id): segment for segment in dataset.segments}
    ride = [
        by_pair[(f"krl:{origin}", f"krl:{destination}")]
        for origin, destination in zip(BOGOR_MAIN, BOGOR_MAIN[1:], strict=False)
    ]

    quote = quote_journey(ride, catalog=DEFAULT_FARE_CATALOG)

    assert quote.status is FareStatus.ESTIMATED
    assert quote.estimated_amount >= 5000


def test_bikun_routes_have_no_orphan_stops_and_are_free() -> None:
    dataset = build_bikun_dataset()
    referenced_stop_ids = {
        stop_id
        for segment in dataset.segments
        for stop_id in (segment.from_stop_id, segment.to_stop_id)
    }

    assert len(dataset.stops) == 10
    assert len(dataset.segments) == 20
    assert {stop.id for stop in dataset.stops} == referenced_stop_ids
    assert {segment.route_id for segment in dataset.segments} == {"bikun:red", "bikun:blue"}
    assert all(segment.fare == 0 for segment in dataset.segments)
    assert all(segment.mode is TransportMode.BIKUN for segment in dataset.segments)
