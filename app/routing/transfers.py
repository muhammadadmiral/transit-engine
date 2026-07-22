"""Sparse in-memory walking interchanges for the routing graph."""

from datetime import date
from math import floor

import networkx as nx

from app.models.schema import (
    DataConfidence,
    Segment,
    ServiceCategory,
    Stop,
    TransportMode,
)

GRID_DEGREES = 0.0025
RAIL_MODES = {TransportMode.KRL, TransportMode.MRT, TransportMode.LRT}
ROAD_FIXED_MODES = {TransportMode.TRANSJAKARTA, TransportMode.JAKLINGKO}
EXPLICIT_TRANSFERS = (
    ("krl:cawang", "lrt-jabodebek:cikoko"),
    ("krl:sudirman", "mrt:dukuh-atas"),
    ("krl:sudirman", "lrt-jabodebek:dukuh-atas"),
    ("mrt:dukuh-atas", "lrt-jabodebek:dukuh-atas"),
    ("krl:universitas-indonesia", "bikun:stasiun-ui"),
)


def add_sparse_fixed_transfers(graph: nx.MultiDiGraph, stops: list[Stop]) -> None:
    """Connect each stop only to its nearest useful stop in another mode."""
    stop_by_id = {stop.id: stop for stop in stops}
    grid: dict[tuple[int, int], list[Stop]] = {}
    for stop in stops:
        grid.setdefault(_cell(stop.lat, stop.lng), []).append(stop)
        graph.add_node(
            stop.id,
            lat=stop.lat,
            lng=stop.lng,
            name=stop.name,
            mode=stop.modes[0].value,
            flexible=False,
        )

    pairs: set[tuple[str, str]] = set()
    for first_id, second_id in EXPLICIT_TRANSFERS:
        if first_id in stop_by_id and second_id in stop_by_id:
            pairs.add(tuple(sorted((first_id, second_id))))

    for stop in stops:
        own_mode = stop.modes[0]
        nearest_by_mode: dict[TransportMode, tuple[float, Stop]] = {}
        for candidate in _nearby_grid(grid, stop.lat, stop.lng, cell_radius=2):
            candidate_mode = candidate.modes[0]
            radius = _transfer_radius(own_mode, candidate_mode)
            if candidate.id == stop.id or radius is None:
                continue
            distance = distance_meters(stop.lat, stop.lng, candidate.lat, candidate.lng)
            if distance > radius:
                continue
            current = nearest_by_mode.get(candidate_mode)
            if current is None or distance < current[0]:
                nearest_by_mode[candidate_mode] = (distance, candidate)
        for _, candidate in nearest_by_mode.values():
            pairs.add(tuple(sorted((stop.id, candidate.id))))

    for first_id, second_id in pairs:
        first, second = stop_by_id[first_id], stop_by_id[second_id]
        add_walking_pair(
            graph,
            first_id,
            second_id,
            (first.lat, first.lng),
            (second.lat, second.lng),
            f"fixed:{first_id}:{second_id}",
        )


def add_walking_pair(
    graph: nx.MultiDiGraph,
    first_id: str,
    second_id: str,
    first: tuple[float, float],
    second: tuple[float, float],
    identity: str,
) -> None:
    distance = distance_meters(first[0], first[1], second[0], second[1])
    duration = max(1.0, distance / 75 + 1)
    first_name = str(graph.nodes[first_id].get("name") or "Titik perpindahan")
    second_name = str(graph.nodes[second_id].get("name") or "Titik perpindahan")
    for suffix, from_id, to_id, from_point, to_point in (
        ("a", first_id, second_id, first, second),
        ("b", second_id, first_id, second, first),
    ):
        segment = Segment(
            id=f"{identity}:{suffix}",
            route_id=identity,
            route_code="WALK",
            route_name="Walking interchange",
            from_stop_id=from_id,
            to_stop_id=to_id,
            mode=TransportMode.WALK,
            service_category=ServiceCategory.TRANSFER,
            service_name="Walking transfer",
            avg_duration_min=duration,
            fare=0,
            fare_product_id="free:walk",
            data_confidence=DataConfidence.COMMUNITY,
            last_verified_at=date.today(),
            color="64748B",
            coordinates=[
                (from_point[1], from_point[0]),
                (to_point[1], to_point[0]),
            ],
            from_stop_name=first_name if from_id == first_id else second_name,
            to_stop_name=second_name if to_id == second_id else first_name,
            from_stop_lat=from_point[0],
            from_stop_lng=from_point[1],
            to_stop_lat=to_point[0],
            to_stop_lng=to_point[1],
        )
        graph.add_edge(from_id, to_id, key=segment.id, segment=segment)


def distance_meters(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    from math import asin, cos, radians, sin, sqrt

    delta_lat = radians(lat2 - lat1)
    delta_lng = radians(lng2 - lng1)
    value = sin(delta_lat / 2) ** 2 + (
        cos(radians(lat1)) * cos(radians(lat2)) * sin(delta_lng / 2) ** 2
    )
    return 2 * 6_371_008.8 * asin(sqrt(value))


def _transfer_radius(
    first_mode: TransportMode, second_mode: TransportMode
) -> float | None:
    if first_mode == second_mode:
        return None
    pair = {first_mode, second_mode}
    if pair <= RAIL_MODES:
        return 500
    if pair & RAIL_MODES and pair & (ROAD_FIXED_MODES | {TransportMode.BIKUN}):
        return 350
    if TransportMode.BIKUN in pair:
        return 250
    if pair == ROAD_FIXED_MODES:
        return 250
    return None


def _cell(lat: float, lng: float) -> tuple[int, int]:
    return floor(lat / GRID_DEGREES), floor(lng / GRID_DEGREES)


def _nearby_grid(
    grid: dict[tuple[int, int], list[Stop]],
    lat: float,
    lng: float,
    *,
    cell_radius: int,
):
    row, column = _cell(lat, lng)
    for row_delta in range(-cell_radius, cell_radius + 1):
        for column_delta in range(-cell_radius, cell_radius + 1):
            yield from grid.get((row + row_delta, column + column_delta), ())
