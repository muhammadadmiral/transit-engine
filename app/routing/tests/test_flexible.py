from datetime import date

from app.models.schema import DataConfidence, FlexibleRoute, Stop, TransportMode
from app.routing.flexible import (
    _resample,
    add_flexible_transfers,
    materialize_flexible_segments,
    nearby_flexible_nodes,
)
from app.routing.graph import build_graph


def route() -> FlexibleRoute:
    return FlexibleRoute(
        id="angkot:test:outbound",
        route_code="T01",
        route_name="Test corridor",
        service_name="Test angkot",
        avg_speed_kmh=18,
        fare=5000,
        fare_product_id="angkot:test",
        data_confidence=DataConfidence.COMMUNITY,
        last_verified_at=date(2026, 7, 22),
        color="F59E0B",
        coordinates=[(106.8, -6.2), (106.81, -6.2)],
    )


def test_flexible_route_materializes_only_in_memory() -> None:
    segments = materialize_flexible_segments([route()])

    assert len(segments) > 2
    assert all(segment.mode is TransportMode.ANGKOT for segment in segments)
    assert all(segment.from_stop_id.startswith("flex:") for segment in segments)
    assert segments[0].coordinates[0] == (106.8, -6.2)
    assert segments[-1].coordinates[-1] == (106.81, -6.2)


def test_pin_and_fixed_transit_connect_to_flexible_corridor() -> None:
    graph = build_graph(materialize_flexible_segments([route()]))
    fixed = Stop(
        id="krl:test",
        name="Test station",
        lat=-6.2002,
        lng=106.805,
        modes=[TransportMode.KRL],
    )
    add_flexible_transfers(graph, [fixed])

    board = nearby_flexible_nodes(
        graph, lat=-6.2001, lng=106.8001, radius_meters=500, can_board=True
    )
    alight = nearby_flexible_nodes(
        graph, lat=-6.2001, lng=106.8099, radius_meters=500, can_board=False
    )

    assert board and board[0].id != alight[0].id
    assert any(str(node).startswith("flex:") for node in graph.successors(fixed.id))


def test_resample_does_not_turn_dense_gis_vertices_into_graph_nodes() -> None:
    dense = [(106.8 + index * 0.00001, -6.2) for index in range(1001)]

    sampled = _resample(dense, 180)

    assert 6 <= len(sampled) <= 8
    assert sampled[0] == dense[0]
    assert sampled[-1] == dense[-1]


def test_parallel_corridors_get_sparse_interchanges_instead_of_a_clique() -> None:
    first = route()
    second = first.model_copy(
        update={
            "id": "angkot:test-2:outbound",
            "route_code": "T02",
            "coordinates": [(106.8, -6.2002), (106.81, -6.2002)],
        }
    )
    graph = build_graph(materialize_flexible_segments([first, second]))

    add_flexible_transfers(graph, [])

    interchange_edges = [
        data["segment"]
        for _, _, data in graph.edges(data=True)
        if data["segment"].id.startswith("flex-flex:")
    ]
    assert 2 <= len(interchange_edges) <= 6


def test_winding_corridor_connects_once_to_the_same_fixed_stop() -> None:
    winding = route().model_copy(
        update={
            "coordinates": [
                (106.8, -6.2),
                (106.805, -6.2),
                (106.805, -6.2002),
                (106.8, -6.2002),
            ]
        }
    )
    graph = build_graph(materialize_flexible_segments([winding]))
    fixed = Stop(
        id="jaklingko:test",
        name="Test roadside stop",
        lat=-6.2001,
        lng=106.8025,
        modes=[TransportMode.JAKLINGKO],
    )

    add_flexible_transfers(graph, [fixed])

    connections = [
        segment
        for _, _, segment in graph.edges(data="segment")
        if segment.id.startswith("flex-fixed:")
    ]
    assert len(connections) == 2
