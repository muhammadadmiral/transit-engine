from app.models.schema import Stop, TransportMode
from app.routing.graph import build_graph
from app.routing.transfers import add_sparse_fixed_transfers


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
