import itertools

import networkx as nx

from app.models.schema import RouteOption, SearchCriteria, Segment
from app.routing.geojson_builder import build_feature_collection
from app.routing.weights import segment_weight


class RouteNotFoundError(ValueError):
    """Raised when no route satisfies the requested transfer limit."""


def find_route(
    graph: nx.MultiDiGraph,
    origin_stop_id: str,
    destination_stop_id: str,
    criteria: SearchCriteria,
    max_transfers: int,
) -> RouteOption:
    if origin_stop_id == destination_stop_id:
        return RouteOption(
            criteria=criteria,
            total_duration_min=0,
            total_fare=0,
            transfer_count=0,
            segments=[],
            geojson=build_feature_collection([]),
        )

    state_graph = _build_state_graph(graph, origin_stop_id, max_transfers)
    destination_states = [
        state for state in state_graph if state[0] == destination_stop_id and state[1] is not None
    ]
    weight = segment_weight(criteria)

    def state_weight(
        source: tuple[str, str | None, int],
        __: tuple[str, str | None, int],
        data: dict[str, object],
    ) -> float:
        segment = data.get("segment")
        if segment is None:
            return 0.0
        if criteria is SearchCriteria.CHEAPEST and source[1] == segment.route_id:
            return 0.0
        return weight(segment)  # type: ignore[arg-type]

    best_path: list[tuple[str, str | None, int]] | None = None
    best_cost = float("inf")
    source = (origin_stop_id, None, 0)
    for destination in destination_states:
        try:
            cost, path = nx.single_source_dijkstra(state_graph, source, destination, weight=state_weight)
        except nx.NetworkXNoPath:
            continue
        if cost < best_cost:
            best_cost, best_path = cost, path

    if best_path is None:
        raise RouteNotFoundError("No route found within max_transfers")

    segments = _segments_from_state_path(state_graph, best_path)
    return RouteOption(
        criteria=criteria,
        total_duration_min=sum(segment.avg_duration_min for segment in segments),
        total_fare=_total_fare(segments),
        transfer_count=best_path[-1][2],
        segments=segments,
        geojson=build_feature_collection(segments),
    )


def _build_state_graph(graph: nx.MultiDiGraph, origin_stop_id: str, max_transfers: int) -> nx.DiGraph:
    state_graph = nx.DiGraph()
    source = (origin_stop_id, None, 0)
    state_graph.add_node(source)
    route_ids = {segment.route_id for segment in _segments(graph)}

    for _, _, edge_data in graph.edges(data=True):
        segment: Segment = edge_data["segment"]
        for previous_route_id, transfers in itertools.product(
            [None, *route_ids], range(max_transfers + 1)
        ):
            if segment.from_stop_id != origin_stop_id and previous_route_id is None:
                continue
            next_transfers = transfers + int(
                previous_route_id is not None and previous_route_id != segment.route_id
            )
            if next_transfers > max_transfers:
                continue
            from_state = (segment.from_stop_id, previous_route_id, transfers)
            to_state = (segment.to_stop_id, segment.route_id, next_transfers)
            state_graph.add_edge(from_state, to_state, segment=segment)
    return state_graph


def _segments_from_state_path(
    graph: nx.DiGraph, states: list[tuple[str, str | None, int]]) -> list[Segment]:
    return [graph[source][target]["segment"] for source, target in zip(states, states[1:], strict=True)]


def _segments(graph: nx.MultiDiGraph) -> list[Segment]:
    return [edge_data["segment"] for _, _, edge_data in graph.edges(data=True)]


def _total_fare(segments: list[Segment]) -> int:
    total = 0
    previous_route_id: str | None = None
    for segment in segments:
        if segment.route_id != previous_route_id:
            total += segment.fare
            previous_route_id = segment.route_id
    return total
