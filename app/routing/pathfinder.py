from collections import deque
from datetime import datetime
from itertools import pairwise

import networkx as nx

from app.fares.catalog import DEFAULT_FARE_CATALOG
from app.fares.engine import FareCatalog, quote_journey
from app.models.schema import PaymentProfile, RouteOption, SearchCriteria, Segment, TransportMode
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
    departure_at: datetime | None = None,
    payment_profile: PaymentProfile = PaymentProfile.STANDARD,
    fare_catalog: FareCatalog = DEFAULT_FARE_CATALOG,
) -> RouteOption:
    if origin_stop_id == destination_stop_id:
        fare_quote = quote_journey(
            [],
            catalog=fare_catalog,
            departure_at=departure_at,
            payment_profile=payment_profile,
        )
        return RouteOption(
            criteria=criteria,
            total_duration_min=0,
            total_fare=0,
            fare_quote=fare_quote,
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
        if criteria is SearchCriteria.CHEAPEST:
            previous_product = state_graph.nodes[source].get("fare_product_id")
            if previous_product is not None and previous_product == segment.fare_product_id:
                return 0.0
        return weight(segment)  # type: ignore[arg-type]

    best_path: list[tuple[str, str | None, int]] | None = None
    best_cost = float("inf")
    source = (origin_stop_id, None, 0)
    for destination in destination_states:
        try:
            cost, path = nx.single_source_dijkstra(
                state_graph, source, destination, weight=state_weight
            )
        except nx.NetworkXNoPath:
            continue
        if cost < best_cost:
            best_cost, best_path = cost, path

    if best_path is None:
        raise RouteNotFoundError("No route found within max_transfers")

    segments = _segments_from_state_path(state_graph, best_path)
    fare_quote = quote_journey(
        segments,
        catalog=fare_catalog,
        departure_at=departure_at,
        payment_profile=payment_profile,
    )
    return RouteOption(
        criteria=criteria,
        total_duration_min=sum(segment.avg_duration_min for segment in segments),
        total_fare=fare_quote.estimated_amount,
        fare_quote=fare_quote,
        transfer_count=best_path[-1][2],
        segments=segments,
        geojson=build_feature_collection(segments),
    )


def _build_state_graph(
    graph: nx.MultiDiGraph, origin_stop_id: str, max_transfers: int
) -> nx.DiGraph:
    state_graph = nx.DiGraph()
    source = (origin_stop_id, None, 0)
    state_graph.add_node(source, fare_product_id=None)
    pending = deque([source])
    visited = {source}

    while pending:
        from_state = pending.popleft()
        stop_id, previous_route_id, transfers = from_state
        for _, _, edge_data in graph.out_edges(stop_id, data=True):
            segment: Segment = edge_data["segment"]
            is_walk = segment.mode is TransportMode.WALK
            next_route_id = previous_route_id if is_walk else segment.route_id
            next_transfers = transfers + int(
                not is_walk
                and previous_route_id is not None
                and previous_route_id != segment.route_id
            )
            if next_transfers > max_transfers:
                continue
            to_state = (segment.to_stop_id, next_route_id, next_transfers)
            previous_product = state_graph.nodes[from_state].get("fare_product_id")
            next_product = previous_product if is_walk else segment.fare_product_id
            state_graph.add_node(to_state, fare_product_id=next_product)
            state_graph.add_edge(from_state, to_state, segment=segment)
            if to_state not in visited:
                visited.add(to_state)
                pending.append(to_state)
    return state_graph


def _segments_from_state_path(
    graph: nx.DiGraph, states: list[tuple[str, str | None, int]]
) -> list[Segment]:
    return [graph[source][target]["segment"] for source, target in pairwise(states)]
