from collections import deque
from datetime import datetime
from itertools import pairwise

import networkx as nx

from app.fares.catalog import DEFAULT_FARE_CATALOG
from app.fares.engine import FareCatalog, quote_journey
from app.models.schema import (
    FareStatus,
    PaymentProfile,
    RouteOption,
    SearchCriteria,
    Segment,
    TransportMode,
)
from app.routing.geojson_builder import build_feature_collection
from app.routing.weights import duration_cost, segment_weight, transfer_penalty


class RouteNotFoundError(ValueError):
    """Raised when no route satisfies the requested transfer limit."""


RouteState = tuple[str, str | None, str | None, int]


def find_route_options(
    graph: nx.MultiDiGraph,
    origin_stop_id: str,
    destination_stop_id: str,
    max_transfers: int,
    departure_at: datetime | None = None,
    payment_profile: PaymentProfile = PaymentProfile.STANDARD,
    fare_catalog: FareCatalog = DEFAULT_FARE_CATALOG,
    additional_segments: list[Segment] | None = None,
) -> list[RouteOption]:
    """Calculate both public objectives while sharing one expanded state graph."""
    prepared_state_graph = _build_state_graph(
        graph,
        origin_stop_id,
        max_transfers,
        additional_segments=additional_segments,
    )
    return [
        find_route(
            graph,
            origin_stop_id,
            destination_stop_id,
            criteria,
            max_transfers,
            departure_at,
            payment_profile,
            fare_catalog,
            additional_segments,
            prepared_state_graph=prepared_state_graph,
        )
        for criteria in (SearchCriteria.FASTEST, SearchCriteria.CHEAPEST)
    ]


def find_route(
    graph: nx.MultiDiGraph,
    origin_stop_id: str,
    destination_stop_id: str,
    criteria: SearchCriteria,
    max_transfers: int,
    departure_at: datetime | None = None,
    payment_profile: PaymentProfile = PaymentProfile.STANDARD,
    fare_catalog: FareCatalog = DEFAULT_FARE_CATALOG,
    additional_segments: list[Segment] | None = None,
    *,
    prepared_state_graph: nx.DiGraph | None = None,
) -> RouteOption:
    extra_segments = additional_segments or []
    extra_nodes = {
        stop_id
        for segment in extra_segments
        for stop_id in (segment.from_stop_id, segment.to_stop_id)
    }
    missing_stops = [
        stop_id
        for stop_id in (origin_stop_id, destination_stop_id)
        if stop_id not in graph and stop_id not in extra_nodes
    ]
    if missing_stops:
        raise RouteNotFoundError(f"Unknown stop: {missing_stops[0]}")
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

    state_graph = prepared_state_graph or _build_state_graph(
        graph, origin_stop_id, max_transfers, additional_segments=extra_segments
    )
    destination_states = [
        state for state in state_graph if state[0] == destination_stop_id and state[1] is not None
    ]
    weight = segment_weight(criteria)
    boarding_costs: dict[str, float] = {}

    def boarding_cost(segment: Segment) -> float:
        if segment.id not in boarding_costs:
            quote = quote_journey(
                [segment],
                catalog=fare_catalog,
                departure_at=departure_at,
                payment_profile=payment_profile,
            )
            amount = segment.fare if quote.status is FareStatus.UNKNOWN else quote.estimated_amount
            boarding_costs[segment.id] = float(amount)
        return boarding_costs[segment.id]

    def state_weight(
        source: RouteState,
        __: RouteState,
        data: dict[str, object],
    ) -> float:
        segment = data.get("segment")
        if segment is None:
            return 0.0
        changes_vehicle = (
            segment.mode is not TransportMode.WALK
            and source[1] is not None
            and source[1] != segment.route_id
        )
        penalty = transfer_penalty(criteria) if changes_vehicle else 0.0
        if criteria is SearchCriteria.CHEAPEST:
            previous_product = source[2]
            if previous_product is not None and previous_product == _fare_identity(segment):
                # Lanjutan produk tarif yang sama: gratis secara tarif, tapi
                # durasinya tetap dihargai agar rute tidak memutar.
                return duration_cost(segment) + penalty  # type: ignore[arg-type]
            return boarding_cost(segment) + duration_cost(segment) + penalty  # type: ignore[arg-type]
        return weight(segment) + penalty  # type: ignore[arg-type]

    source: RouteState = (origin_stop_id, None, None, 0)
    lengths, paths = nx.single_source_dijkstra(state_graph, source, weight=state_weight)
    reachable_destinations = [
        destination for destination in destination_states if destination in lengths
    ]
    if not reachable_destinations:
        raise RouteNotFoundError("No route found within max_transfers")
    best_destination = min(reachable_destinations, key=lengths.__getitem__)
    best_path: list[RouteState] = paths[best_destination]

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
        transfer_count=best_path[-1][3],
        segments=segments,
        geojson=build_feature_collection(segments),
    )


def _build_state_graph(
    graph: nx.MultiDiGraph,
    origin_stop_id: str,
    max_transfers: int,
    *,
    additional_segments: list[Segment] | None = None,
) -> nx.DiGraph:
    state_graph = nx.DiGraph()
    source: RouteState = (origin_stop_id, None, None, 0)
    state_graph.add_node(source)
    pending = deque([source])
    visited = {source}
    extra_outgoing: dict[str, list[Segment]] = {}
    for segment in additional_segments or []:
        extra_outgoing.setdefault(segment.from_stop_id, []).append(segment)

    while pending:
        from_state = pending.popleft()
        stop_id, previous_route_id, previous_product, transfers = from_state
        graph_segments = (
            [edge_data["segment"] for _, _, edge_data in graph.out_edges(stop_id, data=True)]
            if stop_id in graph
            else []
        )
        for segment in [*graph_segments, *extra_outgoing.get(stop_id, [])]:
            is_walk = segment.mode is TransportMode.WALK
            next_route_id = previous_route_id if is_walk else segment.route_id
            next_transfers = transfers + int(
                not is_walk
                and previous_route_id is not None
                and previous_route_id != segment.route_id
            )
            if next_transfers > max_transfers:
                continue
            next_product = previous_product if is_walk else _fare_identity(segment)
            to_state: RouteState = (
                segment.to_stop_id,
                next_route_id,
                next_product,
                next_transfers,
            )
            state_graph.add_node(to_state)
            state_graph.add_edge(from_state, to_state, segment=segment)
            if to_state not in visited:
                visited.add(to_state)
                pending.append(to_state)
    return state_graph


def _segments_from_state_path(graph: nx.DiGraph, states: list[RouteState]) -> list[Segment]:
    return [graph[source][target]["segment"] for source, target in pairwise(states)]


def _fare_identity(segment: Segment) -> str:
    return segment.fare_product_id or f"legacy:{segment.route_id}"
