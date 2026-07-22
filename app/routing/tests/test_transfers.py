from app.models.schema import Stop, TransportMode
from app.routing.graph import build_graph
from app.routing.transfers import (
    UI_EAST_GATE_ID,
    add_curated_access_paths,
    add_sparse_fixed_transfers,
)


def _stop(identity: str, mode: TransportMode, lat: float, lng: float) -> Stop:
    return Stop(id=identity, name=identity, modes=[mode], lat=lat, lng=lng)


def test_sparse_fixed_transfers_choose_only_nearest_stop_per_mode() -> None:
    graph = build_graph([])
    rail = _stop("krl:test", TransportMode.KRL, -6.2, 106.8)
    near = _stop("transjakarta:near", TransportMode.TRANSJAKARTA, -6.2002, 106.8)
    farther = _stop("transjakarta:farther", TransportMode.TRANSJAKARTA, -6.2005, 106.8)

    add_sparse_fixed_transfers(graph, [rail, near, farther])

    assert graph.has_edge(rail.id, near.id)
    assert not graph.has_edge(rail.id, farther.id)


def test_sparse_fixed_transfers_do_not_clique_same_mode_stops() -> None:
    graph = build_graph([])
    stops = [
        _stop(f"jaklingko:{index}", TransportMode.JAKLINGKO, -6.2, 106.8 + index * 0.0001)
        for index in range(12)
    ]

    add_sparse_fixed_transfers(graph, stops)

    assert graph.number_of_edges() == 0


def test_ui_paid_crossing_preserves_instruction_and_curated_geometry() -> None:
    graph = build_graph([])
    graph.add_node(
        "krl:universitas-indonesia",
        name="Universitas Indonesia",
        lat=-6.3605313,
        lng=106.8317755,
    )

    add_curated_access_paths(graph)

    segment = graph.edges[
        "krl:universitas-indonesia", UI_EAST_GATE_ID, "station-access:ui:east"
    ]["segment"]
    assert segment.access_action.value == "paid_station_crossing"
    assert segment.walking_route_source.value == "curated"
    assert segment.fare == 3000
    assert len(segment.coordinates) > 2
