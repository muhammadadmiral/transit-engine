"""In-memory graph adapter for continuous hail-and-ride route corridors."""

from collections import defaultdict
from math import asin, cos, floor, radians, sin, sqrt

import networkx as nx

from app.models.schema import (
    FlexibleRoute,
    NearbyStop,
    Segment,
    Stop,
    TransportMode,
)
from app.routing.transfers import add_walking_pair

SAMPLE_INTERVAL_METERS = 180.0
FIXED_TRANSFER_RADIUS_METERS = 250.0
RAIL_TRANSFER_RADIUS_METERS = 600.0
FLEX_TRANSFER_RADIUS_METERS = 120.0
GRID_DEGREES = 0.0025
TRANSFER_GRID_DEGREES = 0.01


def materialize_flexible_segments(routes: list[FlexibleRoute]) -> list[Segment]:
    """Turn corridors into temporary graph edges, never database stops."""
    result: list[Segment] = []
    for route in routes:
        points = _resample(route.coordinates, SAMPLE_INTERVAL_METERS)
        for index, (first, second) in enumerate(zip(points, points[1:], strict=False)):
            distance = distance_meters(first[1], first[0], second[1], second[0])
            result.append(
                Segment(
                    id=f"{route.id}:edge:{index}",
                    route_id=route.id,
                    route_code=route.route_code,
                    route_name=route.route_name,
                    from_stop_id=f"flex:{route.id}:{index}",
                    to_stop_id=f"flex:{route.id}:{index + 1}",
                    mode=route.mode,
                    service_category=route.service_category,
                    service_name=route.service_name,
                    avg_duration_min=max(0.1, distance / (route.avg_speed_kmh * 1000 / 60)),
                    fare=route.fare,
                    fare_product_id=route.fare_product_id,
                    data_confidence=route.data_confidence,
                    last_verified_at=route.last_verified_at,
                    color=route.color,
                    coordinates=[first, second],
                    from_stop_name=f"Koridor {route.route_code} (naik fleksibel)",
                    to_stop_name=f"Koridor {route.route_code} (turun fleksibel)",
                    from_stop_lat=first[1],
                    from_stop_lng=first[0],
                    to_stop_lat=second[1],
                    to_stop_lng=second[0],
                )
            )
    return result


def add_flexible_transfers(graph: nx.MultiDiGraph, fixed_stops: list[Stop]) -> None:
    """Connect flexible corridor points to nearby fixed transit and corridors."""
    fixed_grid: dict[tuple[int, int], list[Stop]] = defaultdict(list)
    for stop in fixed_stops:
        fixed_grid[_cell(stop.lat, stop.lng)].append(stop)
        graph.add_node(
            stop.id,
            lat=stop.lat,
            lng=stop.lng,
            name=stop.name,
            mode=stop.modes[0].value,
            flexible=False,
        )

    flex_nodes = [
        (node_id, data) for node_id, data in graph.nodes(data=True) if data.get("flexible")
    ]
    for node_id, data in flex_nodes:
        lat, lng = float(data["lat"]), float(data["lng"])
        nearest_by_mode: dict[TransportMode, tuple[float, Stop]] = {}
        for stop in _nearby_grid(fixed_grid, lat, lng, cell_radius=3):
            distance = distance_meters(lat, lng, stop.lat, stop.lng)
            transfer_radius = (
                RAIL_TRANSFER_RADIUS_METERS
                if stop.modes[0] in {TransportMode.KRL, TransportMode.MRT, TransportMode.LRT}
                else FIXED_TRANSFER_RADIUS_METERS
            )
            if distance > transfer_radius:
                continue
            mode = stop.modes[0]
            current = nearest_by_mode.get(mode)
            if current is None or distance < current[0]:
                nearest_by_mode[mode] = (distance, stop)
        for _, stop in nearest_by_mode.values():
            add_walking_pair(
                graph,
                node_id,
                stop.id,
                (lat, lng),
                (stop.lat, stop.lng),
                f"flex-fixed:{node_id}:{stop.id}",
            )

    flex_grid: dict[tuple[int, int], list[tuple[str, dict[str, object]]]] = defaultdict(list)
    for item in flex_nodes:
        flex_grid[_cell(float(item[1]["lat"]), float(item[1]["lng"]))].append(item)
    best_by_route_pair_cell: dict[
        tuple[str, str, int, int],
        tuple[float, str, dict[str, object], str, dict[str, object]],
    ] = {}
    for node_id, data in flex_nodes:
        lat, lng = float(data["lat"]), float(data["lng"])
        nearest_by_route: dict[str, tuple[float, str, dict[str, object]]] = {}
        own_route = str(data["flexible_route_id"])
        for other_id, other in _nearby_grid(flex_grid, lat, lng, cell_radius=1):
            other_route = str(other["flexible_route_id"])
            if other_route == own_route:
                continue
            distance = distance_meters(lat, lng, float(other["lat"]), float(other["lng"]))
            if distance > FLEX_TRANSFER_RADIUS_METERS:
                continue
            if other_route not in nearest_by_route or distance < nearest_by_route[other_route][0]:
                nearest_by_route[other_route] = (distance, other_id, other)
        for distance, other_id, other in nearest_by_route.values():
            other_route = str(other["flexible_route_id"])
            route_pair = tuple(sorted((own_route, other_route)))
            other_lat, other_lng = float(other["lat"]), float(other["lng"])
            cell = _transfer_cell((lat + other_lat) / 2, (lng + other_lng) / 2)
            key = (route_pair[0], route_pair[1], cell[0], cell[1])
            current = best_by_route_pair_cell.get(key)
            if current is None or distance < current[0]:
                best_by_route_pair_cell[key] = (distance, node_id, data, other_id, other)

    seen_node_pairs: set[tuple[str, str]] = set()
    for _, first_id, first, second_id, second in best_by_route_pair_cell.values():
        node_pair = tuple(sorted((first_id, second_id)))
        if node_pair in seen_node_pairs:
            continue
        seen_node_pairs.add(node_pair)
        add_walking_pair(
            graph,
            first_id,
            second_id,
            (float(first["lat"]), float(first["lng"])),
            (float(second["lat"]), float(second["lng"])),
            f"flex-flex:{node_pair[0]}:{node_pair[1]}",
        )


def nearby_flexible_nodes(
    graph: nx.MultiDiGraph,
    *,
    lat: float,
    lng: float,
    radius_meters: int,
    can_board: bool,
    limit: int = 32,
) -> list[NearbyStop]:
    """Return the nearest continuous boarding projection per directed route."""
    best_by_route: dict[str, tuple[float, str, dict[str, object]]] = {}
    for node_id, data in graph.nodes(data=True):
        if not data.get("flexible"):
            continue
        route_id = str(data["flexible_route_id"])
        if can_board and not _has_flexible_edge(graph, node_id, route_id, outgoing=True):
            continue
        if not can_board and not _has_flexible_edge(graph, node_id, route_id, outgoing=False):
            continue
        distance = distance_meters(lat, lng, float(data["lat"]), float(data["lng"]))
        if distance > radius_meters:
            continue
        if route_id not in best_by_route or distance < best_by_route[route_id][0]:
            best_by_route[route_id] = (distance, node_id, data)
    candidates = sorted(best_by_route.values(), key=lambda item: item[0])[:limit]
    return [
        NearbyStop(
            id=node_id,
            name=str(data["name"]),
            lat=float(data["lat"]),
            lng=float(data["lng"]),
            modes=[TransportMode.ANGKOT],
            distance_meters=round(distance, 1),
            can_board=can_board,
            can_alight=not can_board,
        )
        for distance, node_id, data in candidates
    ]


def _has_flexible_edge(
    graph: nx.MultiDiGraph, node_id: str, route_id: str, *, outgoing: bool
) -> bool:
    edges = graph.out_edges(node_id, data=True) if outgoing else graph.in_edges(node_id, data=True)
    return any(
        data["segment"].mode is TransportMode.ANGKOT and data["segment"].route_id == route_id
        for _, _, data in edges
    )


def _resample(
    coordinates: list[tuple[float, float]], interval_meters: float
) -> list[tuple[float, float]]:
    """Sample by cumulative distance without retaining every dense GIS vertex."""
    result = [coordinates[0]]
    distance_since_sample = 0.0
    first = coordinates[0]
    for raw_second in coordinates[1:]:
        second = raw_second
        segment_distance = distance_meters(first[1], first[0], second[1], second[0])
        while segment_distance > 0 and distance_since_sample + segment_distance >= interval_meters:
            needed = interval_meters - distance_since_sample
            ratio = needed / segment_distance
            point = (
                first[0] + (second[0] - first[0]) * ratio,
                first[1] + (second[1] - first[1]) * ratio,
            )
            if point != result[-1]:
                result.append(point)
            first = point
            segment_distance -= needed
            distance_since_sample = 0.0
        distance_since_sample += segment_distance
        first = second
    if coordinates[-1] != result[-1]:
        result.append(coordinates[-1])
    return result


def _cell(lat: float, lng: float) -> tuple[int, int]:
    return floor(lat / GRID_DEGREES), floor(lng / GRID_DEGREES)


def _transfer_cell(lat: float, lng: float) -> tuple[int, int]:
    return floor(lat / TRANSFER_GRID_DEGREES), floor(lng / TRANSFER_GRID_DEGREES)


def _nearby_grid(grid: dict, lat: float, lng: float, *, cell_radius: int):
    row, column = _cell(lat, lng)
    for row_delta in range(-cell_radius, cell_radius + 1):
        for column_delta in range(-cell_radius, cell_radius + 1):
            yield from grid.get((row + row_delta, column + column_delta), ())


def distance_meters(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    delta_lat = radians(lat2 - lat1)
    delta_lng = radians(lng2 - lng1)
    value = sin(delta_lat / 2) ** 2 + (
        cos(radians(lat1)) * cos(radians(lat2)) * sin(delta_lng / 2) ** 2
    )
    return 2 * 6_371_008.8 * asin(sqrt(value))
