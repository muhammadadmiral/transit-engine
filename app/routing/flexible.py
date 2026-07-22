"""In-memory graph adapter for continuous hail-and-ride route corridors."""

from collections import defaultdict
from datetime import date
from math import asin, cos, floor, radians, sin, sqrt

import networkx as nx

from app.models.schema import (
    DataConfidence,
    FlexibleRoute,
    NearbyStop,
    Segment,
    ServiceCategory,
    Stop,
    TransportMode,
)

SAMPLE_INTERVAL_METERS = 180.0
FIXED_TRANSFER_RADIUS_METERS = 250.0
RAIL_TRANSFER_RADIUS_METERS = 600.0
FLEX_TRANSFER_RADIUS_METERS = 120.0
GRID_DEGREES = 0.0025


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
        for stop in _nearby_grid(fixed_grid, lat, lng, cell_radius=3):
            distance = distance_meters(lat, lng, stop.lat, stop.lng)
            transfer_radius = (
                RAIL_TRANSFER_RADIUS_METERS
                if stop.modes[0] in {TransportMode.KRL, TransportMode.MRT, TransportMode.LRT}
                else FIXED_TRANSFER_RADIUS_METERS
            )
            if distance <= transfer_radius:
                _add_walking_pair(
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
    seen: set[tuple[str, str]] = set()
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
        for _, other_id, other in nearest_by_route.values():
            pair = tuple(sorted((node_id, other_id)))
            if pair in seen:
                continue
            seen.add(pair)
            _add_walking_pair(
                graph,
                node_id,
                other_id,
                (lat, lng),
                (float(other["lat"]), float(other["lng"])),
                f"flex-flex:{pair[0]}:{pair[1]}",
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


def _add_walking_pair(
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
            route_name="Walk to/from flexible corridor",
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
            coordinates=[(from_point[1], from_point[0]), (to_point[1], to_point[0])],
            from_stop_name=first_name if from_id == first_id else second_name,
            to_stop_name=second_name if to_id == second_id else first_name,
            from_stop_lat=from_point[0],
            from_stop_lng=from_point[1],
            to_stop_lat=to_point[0],
            to_stop_lng=to_point[1],
        )
        graph.add_edge(from_id, to_id, key=segment.id, segment=segment)


def _cell(lat: float, lng: float) -> tuple[int, int]:
    return floor(lat / GRID_DEGREES), floor(lng / GRID_DEGREES)


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
