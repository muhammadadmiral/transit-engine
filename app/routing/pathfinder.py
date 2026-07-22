from collections import deque
from datetime import datetime
from heapq import heappop, heappush
from itertools import count
from math import asin, cos, radians, sin, sqrt

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
from app.routing.schedules import ServiceFrequencyIndex, apply_scheduled_waits
from app.routing.stop_directory import StopSummary
from app.routing.traffic import historical_traffic_factor
from app.routing.weights import WALKING_RELUCTANCE, duration_cost, transfer_penalty


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
    stop_directory: "dict[str, StopSummary] | None" = None,
    schedule_index: ServiceFrequencyIndex | None = None,
) -> list[RouteOption]:
    """Calculate both public objectives without materializing the expanded graph."""
    options = [
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
            schedule_index,
        )
        for criteria in (SearchCriteria.FASTEST, SearchCriteria.CHEAPEST)
    ]
    if stop_directory is not None:
        for option in options:
            _apply_stop_directory(option, stop_directory)
    return options


def _apply_stop_directory(option: RouteOption, directory: "dict[str, StopSummary]") -> None:
    """Mutate a route option's segments so the UI can show names + coordinates
    rather than the raw internal stop IDs."""
    enriched: list[Segment] = []
    for segment in option.segments:
        from_entry = directory.get(segment.from_stop_id)
        to_entry = directory.get(segment.to_stop_id)
        enriched.append(
            segment.model_copy(
                update={
                    "from_stop_name": from_entry.name if from_entry else segment.from_stop_name,
                    "to_stop_name": to_entry.name if to_entry else segment.to_stop_name,
                    "from_stop_lat": from_entry.lat if from_entry else None,
                    "from_stop_lng": from_entry.lng if from_entry else None,
                    "to_stop_lat": to_entry.lat if to_entry else None,
                    "to_stop_lng": to_entry.lng if to_entry else None,
                }
            )
        )
    option.segments = enriched


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
    schedule_index: ServiceFrequencyIndex | None = None,
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

    extra_outgoing: dict[str, list[Segment]] = {}
    extra_incoming: dict[str, list[Segment]] = {}
    for segment in extra_segments:
        extra_outgoing.setdefault(segment.from_stop_id, []).append(segment)
        extra_incoming.setdefault(segment.to_stop_id, []).append(segment)
    reachable = _reverse_reachable(graph, destination_stop_id, extra_incoming)
    if origin_stop_id not in reachable:
        raise RouteNotFoundError("No route found within max_transfers")
    destination_coordinates = _node_coordinates(
        graph, destination_stop_id, extra_incoming.get(destination_stop_id, [])
    )
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

    def state_weight(source: RouteState, segment: Segment) -> float:
        changes_vehicle = (
            segment.mode is not TransportMode.WALK
            and source[1] is not None
            and source[1] != segment.route_id
        )
        penalty = transfer_penalty(criteria) if changes_vehicle else 0.0
        wait = 0.0
        if segment.mode is not TransportMode.WALK and source[1] != segment.route_id:
            wait, _ = (
                schedule_index.expected_wait(segment, departure_at)
                if schedule_index is not None
                else (0.0, None)
            )
        if criteria is SearchCriteria.CHEAPEST:
            previous_product = source[2]
            if previous_product is not None and previous_product == _fare_identity(segment):
                # Lanjutan produk tarif yang sama: gratis secara tarif, tapi
                # durasinya tetap dihargai agar rute tidak memutar.
                return (
                    duration_cost(segment)
                    * _mode_reluctance(segment)
                    * historical_traffic_factor(segment, departure_at)
                    + wait * 50
                    + penalty
                )
            return (
                boarding_cost(segment)
                + duration_cost(segment)
                * _mode_reluctance(segment)
                * historical_traffic_factor(segment, departure_at)
                + wait * 50
                + penalty
            )
        return (
            segment.avg_duration_min
            * _mode_reluctance(segment)
            * historical_traffic_factor(segment, departure_at)
            + wait
            + float(segment.fare) * 0.000001
            + penalty
        )

    def heuristic(stop_id: str) -> float:
        if destination_coordinates is None:
            return 0.0
        current = _node_coordinates(graph, stop_id, extra_incoming.get(stop_id, []))
        if current is None:
            return 0.0
        # 160 km/h is deliberately above every supported scheduled mode, making
        # this an admissible lower bound while still guiding long regional searches.
        minutes = _distance_km(current, destination_coordinates) / 160 * 60
        return minutes if criteria is SearchCriteria.FASTEST else minutes * 50

    source: RouteState = (origin_stop_id, None, None, 0)
    queue: list[tuple[float, int, float, RouteState]] = [
        (heuristic(origin_stop_id), 0, 0.0, source)
    ]
    sequence = count(1)
    distances = {source: 0.0}
    labels: dict[tuple[str, str | None, str | None], dict[int, float]] = {source[:3]: {0: 0.0}}
    previous: dict[RouteState, tuple[RouteState, Segment]] = {}
    best_destination: RouteState | None = None

    while queue:
        _, _, cost, state = heappop(queue)
        if cost != distances.get(state):
            continue
        stop_id, previous_route_id, previous_product, transfers = state
        if stop_id == destination_stop_id and previous_route_id is not None:
            best_destination = state
            break

        graph_segments = (
            [data["segment"] for _, _, data in graph.out_edges(stop_id, data=True)]
            if stop_id in graph
            else []
        )
        for segment in [*graph_segments, *extra_outgoing.get(stop_id, [])]:
            if segment.to_stop_id not in reachable:
                continue
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
            next_state: RouteState = (
                segment.to_stop_id,
                next_route_id,
                next_product,
                next_transfers,
            )
            next_cost = cost + state_weight(state, segment)
            if next_cost >= distances.get(next_state, float("inf")):
                continue
            core = next_state[:3]
            core_labels = labels.setdefault(core, {})
            if any(
                used_transfers <= next_transfers and label_cost <= next_cost
                for used_transfers, label_cost in core_labels.items()
            ):
                continue
            for used_transfers, label_cost in list(core_labels.items()):
                if used_transfers >= next_transfers and label_cost >= next_cost:
                    distances.pop((*core, used_transfers), None)
                    del core_labels[used_transfers]
            core_labels[next_transfers] = next_cost
            distances[next_state] = next_cost
            previous[next_state] = (state, segment)
            heappush(
                queue,
                (next_cost + heuristic(segment.to_stop_id), next(sequence), next_cost, next_state),
            )

    if best_destination is None:
        raise RouteNotFoundError("No route found within max_transfers")

    segments: list[Segment] = []
    cursor = best_destination
    while cursor != source:
        cursor, segment = previous[cursor]
        segments.append(segment)
    segments.reverse()
    segments = apply_scheduled_waits(segments, schedule_index, departure_at)
    fare_quote = quote_journey(
        segments,
        catalog=fare_catalog,
        departure_at=departure_at,
        payment_profile=payment_profile,
    )
    return RouteOption(
        criteria=criteria,
        total_duration_min=sum(
            segment.avg_duration_min + segment.scheduled_wait_min for segment in segments
        ),
        total_fare=fare_quote.estimated_amount,
        fare_quote=fare_quote,
        transfer_count=best_destination[3],
        segments=segments,
        geojson=build_feature_collection(segments),
    )


def _fare_identity(segment: Segment) -> str:
    product = segment.fare_product_id or f"legacy:{segment.route_id}"
    return f"{product}:{segment.route_id}" if segment.mode is TransportMode.ANGKOT else product


def _mode_reluctance(segment: Segment) -> float:
    return WALKING_RELUCTANCE if segment.mode is TransportMode.WALK else 1.0


def _reverse_reachable(
    graph: nx.MultiDiGraph,
    destination_stop_id: str,
    extra_incoming: dict[str, list[Segment]],
) -> set[str]:
    """Find nodes that can reach the destination before expanding fare/transfer state."""
    reachable = {destination_stop_id}
    queue = deque([destination_stop_id])
    while queue:
        stop_id = queue.popleft()
        predecessors = list(graph.predecessors(stop_id)) if stop_id in graph else []
        predecessors.extend(segment.from_stop_id for segment in extra_incoming.get(stop_id, []))
        for predecessor in predecessors:
            if predecessor not in reachable:
                reachable.add(predecessor)
                queue.append(predecessor)
    return reachable


def _node_coordinates(
    graph: nx.MultiDiGraph, stop_id: str, incoming: list[Segment]
) -> tuple[float, float] | None:
    if stop_id in graph:
        data = graph.nodes[stop_id]
        if data.get("lat") is not None and data.get("lng") is not None:
            return float(data["lat"]), float(data["lng"])
    if incoming:
        lng, lat = incoming[0].coordinates[-1]
        return lat, lng
    return None


def _distance_km(first: tuple[float, float], second: tuple[float, float]) -> float:
    lat1, lng1 = first
    lat2, lng2 = second
    delta_lat = radians(lat2 - lat1)
    delta_lng = radians(lng2 - lng1)
    value = sin(delta_lat / 2) ** 2 + (
        cos(radians(lat1)) * cos(radians(lat2)) * sin(delta_lng / 2) ** 2
    )
    return 2 * 6371.0088 * asin(sqrt(value))
