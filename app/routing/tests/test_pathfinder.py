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
    fare_product_id: str | None = None,
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
        fare_product_id=fare_product_id,
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


@pytest.mark.parametrize("origin,destination", [("unknown", "destination"), ("origin", "unknown")])
def test_rejects_unknown_origin_or_destination(origin: str, destination: str) -> None:
    graph = build_graph([segment("ride", "origin", "destination", TransportMode.MRT, 4, 4000)])

    with pytest.raises(RouteNotFoundError, match="Unknown stop"):
        find_route(graph, origin, destination, SearchCriteria.FASTEST, max_transfers=0)


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


def test_transfer_within_one_fare_product_is_not_charged_twice() -> None:
    graph = build_graph(
        [
            segment(
                "one",
                "origin",
                "mid",
                TransportMode.TRANSJAKARTA,
                4,
                3500,
                "tj-1",
                "transjakarta:regular",
            ),
            segment(
                "two",
                "mid",
                "destination",
                TransportMode.TRANSJAKARTA,
                4,
                3500,
                "tj-2",
                "transjakarta:regular",
            ),
        ]
    )

    route = find_route(graph, "origin", "destination", SearchCriteria.CHEAPEST, max_transfers=1)

    assert route.total_fare == 3500
    assert route.transfer_count == 1


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


def test_transfer_penalty_prefers_a_slightly_slower_direct_vehicle() -> None:
    graph = build_graph(
        [
            segment("first", "origin", "mid", TransportMode.MRT, 5, 4000, "mrt-a"),
            segment("second", "mid", "destination", TransportMode.KRL, 5, 3000, "krl-b"),
            segment(
                "direct",
                "origin",
                "destination",
                TransportMode.TRANSJAKARTA,
                15,
                3500,
                "tj-direct",
            ),
        ]
    )

    route = find_route(graph, "origin", "destination", SearchCriteria.FASTEST, max_transfers=1)

    assert [item.id for item in route.segments] == ["direct"]
    assert route.transfer_count == 0


def test_coordinate_access_can_choose_a_farther_but_better_stop() -> None:
    graph = build_graph(
        [
            segment("detour", "near", "destination-stop", TransportMode.TRANSJAKARTA, 40, 3500),
            segment("direct", "rail", "destination-stop", TransportMode.KRL, 10, 3000),
        ]
    )
    access = [
        segment("walk-near", "pin", "near", TransportMode.WALK, 1, 0, "access"),
        segment("walk-rail", "pin", "rail", TransportMode.WALK, 7, 0, "access"),
        segment(
            "walk-destination",
            "destination-stop",
            "destination-pin",
            TransportMode.WALK,
            2,
            0,
            "access",
        ),
    ]

    route = find_route(
        graph,
        "pin",
        "destination-pin",
        SearchCriteria.FASTEST,
        max_transfers=1,
        additional_segments=access,
    )

    assert [item.id for item in route.segments] == [
        "walk-rail",
        "direct",
        "walk-destination",
    ]


def test_cheapest_uses_fare_product_rule_when_raw_gtfs_fare_is_zero() -> None:
    graph = build_graph(
        [
            segment(
                "free-looking-tj",
                "origin",
                "destination",
                TransportMode.TRANSJAKARTA,
                20,
                0,
                "tj",
                "transjakarta:regular",
            ),
            segment(
                "krl",
                "origin",
                "destination",
                TransportMode.KRL,
                25,
                3000,
                "krl",
                "krl-jabodetabek:regular",
            ),
        ]
    )

    route = find_route(graph, "origin", "destination", SearchCriteria.CHEAPEST, max_transfers=0)

    assert [item.id for item in route.segments] == ["krl"]
    assert route.total_fare == 3000


def test_cheapest_penalizes_a_free_tj_detour_against_a_priced_rail_route() -> None:
    """Regression: SMAN 38 -> Jakarta Kota — cheapest previously routed the
    user on a multi-stop TransJakarta marathon (142 min, Rp3.500) instead of
    walking ~1 min to KRL Universitas Pancasila (44 min, Rp4.000).

    The Rp500 fare saving must not buy hours of extra riding time.
    """
    graph = build_graph(
        [
            # 1-stop KRL leg as in the real network.
            segment(
                "krl-leg",
                "krl:universitas-pancasila",
                "krl:jakarta-kota",
                TransportMode.KRL,
                40,
                3000,
                "krl-bogor",
                "krl-jabodetabek:regular",
            ),
            # Free TransJakarta BRT legs that form a long detour loop.
            *[
                segment(
                    f"tj-{index}",
                    f"tj:{index}",
                    f"tj:{index + 1}",
                    TransportMode.TRANSJAKARTA,
                    3,
                    3500,
                    "tj-detour",
                    "transjakarta:regular",
                )
                for index in range(20)
            ],
        ]
    )
    # Connect the long TJ chain to both ends.
    access = [
        segment(
            "walk-rail", "pin", "krl:universitas-pancasila", TransportMode.WALK, 1, 0, "access"
        ),
        segment("walk-tj-head", "pin", "tj:0", TransportMode.WALK, 1, 0, "access"),
        segment(
            "walk-destination",
            "krl:jakarta-kota",
            "destination-pin",
            TransportMode.WALK,
            2,
            0,
            "access",
        ),
        segment(
            "walk-tj-tail",
            "tj:20",
            "destination-pin",
            TransportMode.WALK,
            8,
            0,
            "access",
        ),
    ]

    fastest = find_route(
        graph,
        "pin",
        "destination-pin",
        SearchCriteria.FASTEST,
        max_transfers=1,
        additional_segments=access,
    )
    cheapest = find_route(
        graph,
        "pin",
        "destination-pin",
        SearchCriteria.CHEAPEST,
        max_transfers=1,
        additional_segments=access,
    )

    assert [item.id for item in fastest.segments[0:1]] == ["walk-rail"]
    assert [item.id for item in cheapest.segments[0:1]] == ["walk-rail"]
    # Detour costs >40 minutes more — cheapest should not take it.
    assert cheapest.total_duration_min < 50
    # Walk legs are free; KRL leg is the only paid segment (Rp3.000).
    assert cheapest.total_fare == 3000


def test_walking_connector_counts_one_boarding_transfer_and_has_no_fare() -> None:
    graph = build_graph(
        [
            segment("mrt", "origin", "mrt-stop", TransportMode.MRT, 4, 4000, "mrt"),
            segment(
                "walk",
                "mrt-stop",
                "krl-stop",
                TransportMode.WALK,
                5,
                0,
                "transfer",
                "free:walk",
            ),
            segment("krl", "krl-stop", "destination", TransportMode.KRL, 6, 3000, "krl"),
        ]
    )

    route = find_route(graph, "origin", "destination", SearchCriteria.FASTEST, max_transfers=1)

    assert [item.mode for item in route.segments] == [
        TransportMode.MRT,
        TransportMode.WALK,
        TransportMode.KRL,
    ]
    assert route.transfer_count == 1
    assert route.total_fare == 7000
    assert all(
        component.fare_product_id != "free:walk" for component in route.fare_quote.components
    )

    with pytest.raises(RouteNotFoundError):
        find_route(graph, "origin", "destination", SearchCriteria.FASTEST, max_transfers=0)
