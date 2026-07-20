from datetime import date

import pytest

from app.models.schema import (
    DataConfidence,
    SearchCriteria,
    Segment,
    ServiceCategory,
    TransportMode,
)
from app.routing.graph import build_graph
from app.routing.pathfinder import RouteNotFoundError, find_route


def segment(
    segment_id: str,
    from_stop_id: str,
    to_stop_id: str,
    mode: TransportMode,
    duration: float,
    fare: int,
    route_id: str | None = None,
) -> Segment:
    return Segment(
        id=segment_id,
        route_id=route_id or mode.value,
        from_stop_id=from_stop_id,
        to_stop_id=to_stop_id,
        mode=mode,
        service_category=ServiceCategory.MAIN,
        service_name=mode.value.upper(),
        avg_duration_min=duration,
        fare=fare,
        data_confidence=DataConfidence.OFFICIAL,
        last_verified_at=date(2026, 7, 19),
        color="00609C",
        coordinates=[(106.8, -6.2), (106.81, -6.21)],
    )


def test_finds_fastest_and_cheapest_routes_independently() -> None:
    graph = build_graph(
        [
            segment("fast-a", "origin", "mid", TransportMode.MRT, 4, 8000),
            segment("fast-b", "mid", "destination", TransportMode.MRT, 4, 8000),
            segment("cheap", "origin", "destination", TransportMode.TRANSJAKARTA, 14, 3500),
        ]
    )

    fastest = find_route(graph, "origin", "destination", SearchCriteria.FASTEST, max_transfers=1)
    cheapest = find_route(graph, "origin", "destination", SearchCriteria.CHEAPEST, max_transfers=1)

    assert [item.id for item in fastest.segments] == ["fast-a", "fast-b"]
    assert fastest.total_duration_min == 8
    assert [item.id for item in cheapest.segments] == ["cheap"]
    assert cheapest.total_fare == 3500


def test_charges_once_and_does_not_count_a_transfer_within_one_route() -> None:
    graph = build_graph(
        [
            segment("one", "origin", "mid", TransportMode.TRANSJAKARTA, 4, 3500, "tj-1"),
            segment("two", "mid", "destination", TransportMode.TRANSJAKARTA, 4, 3500, "tj-1"),
        ]
    )

    route = find_route(graph, "origin", "destination", SearchCriteria.CHEAPEST, max_transfers=0)

    assert route.total_fare == 3500
    assert route.transfer_count == 0


def test_counts_a_transfer_between_two_routes_of_the_same_mode() -> None:
    graph = build_graph(
        [
            segment("one", "origin", "mid", TransportMode.TRANSJAKARTA, 4, 3500, "tj-1"),
            segment("two", "mid", "destination", TransportMode.TRANSJAKARTA, 4, 3500, "tj-2"),
        ]
    )

    with pytest.raises(RouteNotFoundError):
        find_route(graph, "origin", "destination", SearchCriteria.FASTEST, max_transfers=0)


def test_respects_max_transfers() -> None:
    graph = build_graph(
        [
            segment("one", "origin", "mid", TransportMode.MRT, 4, 4000),
            segment("two", "mid", "destination", TransportMode.KRL, 4, 4000),
        ]
    )

    try:
        find_route(graph, "origin", "destination", SearchCriteria.FASTEST, max_transfers=0)
    except RouteNotFoundError:
        pass
    else:
        raise AssertionError("expected transfer constraint to reject the route")
