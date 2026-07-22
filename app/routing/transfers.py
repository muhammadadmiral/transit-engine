"""Sparse in-memory walking interchanges for the routing graph."""

from datetime import date
from math import floor

import networkx as nx

from app.models.schema import (
    AccessAction,
    DataConfidence,
    NearbyStop,
    Segment,
    ServiceCategory,
    Stop,
    TransportMode,
    WalkingRouteSource,
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

UI_KRL_STOP_ID = "krl:universitas-indonesia"
UI_EAST_GATE_ID = "access:stasiun-ui:gate-margonda"
UI_EAST_GATE = (-6.3613005, 106.8320277)
UI_TRACK_BARRIER_LNG = 106.83190
UI_PAID_CROSSING_GEOMETRY = [
    (106.8317755, -6.3605313),
    (106.8317569, -6.3609118),
    (106.8317882, -6.3611351),
    (106.8318153, -6.3613236),
    (106.8318384, -6.3613206),
    (106.8318118, -6.3611256),
    (106.8319930, -6.3611038),
    (106.8320277, -6.3613005),
]

LA_KRL_STOP_ID = "krl:lenteng-agung"
LA_EAST_GATE_ID = "access:stasiun-lenteng-agung:east"
LA_EAST_GATE = (-6.3306245, 106.835150)
LA_WEST_GATE_ID = "access:stasiun-lenteng-agung:west"
LA_WEST_GATE = (-6.3306245, 106.834450)
LA_CROSSING_GEOMETRY = [
    (106.834450, -6.3306245),
    (106.8348170, -6.3306245),
    (106.835150, -6.3306245),
]


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

    explicit_pairs: set[tuple[str, str]] = set()
    for first_id, second_id in EXPLICIT_TRANSFERS:
        if first_id in stop_by_id and second_id in stop_by_id:
            explicit_pairs.add(tuple(sorted((first_id, second_id))))
    pairs = set(explicit_pairs)

    selections: dict[str, dict[TransportMode, Stop]] = {}
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
        selections[stop.id] = {
            mode: candidate for mode, (_, candidate) in nearest_by_mode.items()
        }

    # Mutual nearest neighbours prevent one station from becoming a clique of
    # every nearby directional stop while retaining the shortest interchange.
    for stop in stops:
        own_mode = stop.modes[0]
        for candidate in selections[stop.id].values():
            reciprocal = selections.get(candidate.id, {}).get(own_mode)
            if reciprocal is not None and reciprocal.id == stop.id:
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
            curated=(first_id, second_id) in explicit_pairs,
        )


def add_curated_access_paths(graph: nx.MultiDiGraph) -> None:
    """Add paid-area station paths that generic street routers cannot model."""
    if UI_KRL_STOP_ID not in graph:
        return
    _prune_ui_barrier_shortcuts(graph)
    graph.add_node(
        UI_EAST_GATE_ID,
        lat=UI_EAST_GATE[0],
        lng=UI_EAST_GATE[1],
        name="Pintu Margonda / Jalan Pepaya Stasiun UI",
        mode=TransportMode.WALK.value,
        flexible=False,
        endpoint_access=True,
    )
    distance = _geometry_distance_meters(UI_PAID_CROSSING_GEOMETRY)
    for suffix, from_id, to_id, coordinates, instruction in (
        (
            "east",
            UI_KRL_STOP_ID,
            UI_EAST_GATE_ID,
            UI_PAID_CROSSING_GEOMETRY,
            "Tap masuk Stasiun UI, menyeberang melalui area peron, lalu tap keluar "
            "di pintu Margonda/Jalan Pepaya.",
        ),
        (
            "west",
            UI_EAST_GATE_ID,
            UI_KRL_STOP_ID,
            list(reversed(UI_PAID_CROSSING_GEOMETRY)),
            "Tap masuk dari pintu Margonda/Jalan Pepaya, menyeberang melalui area "
            "peron, lalu tap keluar ke sisi kampus UI.",
        ),
    ):
        segment = Segment(
            id=f"station-access:ui:{suffix}",
            route_id="station-access:ui-paid-crossing",
            route_code="GATE",
            route_name="Penyeberangan berbayar Stasiun UI",
            from_stop_id=from_id,
            to_stop_id=to_id,
            mode=TransportMode.WALK,
            service_category=ServiceCategory.TRANSFER,
            service_name="Penyeberangan berbayar Stasiun UI",
            avg_duration_min=3.5,
            fare=3000,
            fare_product_id="krl:station-crossing",
            data_confidence=DataConfidence.COMMUNITY,
            last_verified_at=date(2026, 7, 22),
            color="A78BFA",
            coordinates=coordinates,
            from_stop_name=str(graph.nodes[from_id].get("name") or from_id),
            to_stop_name=str(graph.nodes[to_id].get("name") or to_id),
            from_stop_lat=coordinates[0][1],
            from_stop_lng=coordinates[0][0],
            to_stop_lat=coordinates[-1][1],
            to_stop_lng=coordinates[-1][0],
            walking_distance_meters=distance,
            distance_meters=distance,
            walking_route_source=WalkingRouteSource.CURATED,
            access_action=AccessAction.PAID_STATION_CROSSING,
            instruction=instruction,
        )
        graph.add_edge(
            segment.from_stop_id,
            segment.to_stop_id,
            key=segment.id,
            segment=segment,
        )

    if LA_KRL_STOP_ID not in graph:
        return

    graph.add_node(
        LA_EAST_GATE_ID,
        lat=LA_EAST_GATE[0],
        lng=LA_EAST_GATE[1],
        name="Jalan Raya Lenteng Agung (Arah Depok)",
        mode=TransportMode.WALK.value,
        flexible=False,
        endpoint_access=True,
    )
    graph.add_node(
        LA_WEST_GATE_ID,
        lat=LA_WEST_GATE[0],
        lng=LA_WEST_GATE[1],
        name="Jalan Raya Lenteng Agung (Arah Pasar Minggu)",
        mode=TransportMode.WALK.value,
        flexible=False,
        endpoint_access=True,
    )

    for suffix, from_id, to_id, coordinates, instruction in (
        (
            "east",
            LA_KRL_STOP_ID,
            LA_EAST_GATE_ID,
            LA_CROSSING_GEOMETRY[1:],
            "Gunakan JPO Stasiun Lenteng Agung menuju sisi Timur (arah Depok).",
        ),
        (
            "east-rev",
            LA_EAST_GATE_ID,
            LA_KRL_STOP_ID,
            list(reversed(LA_CROSSING_GEOMETRY[1:])),
            "Gunakan JPO masuk ke Stasiun Lenteng Agung.",
        ),
        (
            "west",
            LA_KRL_STOP_ID,
            LA_WEST_GATE_ID,
            list(reversed(LA_CROSSING_GEOMETRY[:2])),
            "Gunakan JPO Stasiun Lenteng Agung menuju sisi Barat (arah Pasar Minggu).",
        ),
        (
            "west-rev",
            LA_WEST_GATE_ID,
            LA_KRL_STOP_ID,
            LA_CROSSING_GEOMETRY[:2],
            "Gunakan JPO masuk ke Stasiun Lenteng Agung.",
        ),
        (
            "cross-east",
            LA_WEST_GATE_ID,
            LA_EAST_GATE_ID,
            LA_CROSSING_GEOMETRY,
            "Gunakan JPO Tapal Kuda untuk menyeberang ke sisi arah Depok.",
        ),
        (
            "cross-west",
            LA_EAST_GATE_ID,
            LA_WEST_GATE_ID,
            list(reversed(LA_CROSSING_GEOMETRY)),
            "Gunakan JPO Tapal Kuda untuk menyeberang ke sisi arah Pasar Minggu.",
        ),
    ):
        segment = Segment(
            id=f"station-access:la:{suffix}",
            route_id="station-access:la-crossing",
            route_code="JPO",
            route_name="JPO Lenteng Agung",
            from_stop_id=from_id,
            to_stop_id=to_id,
            mode=TransportMode.WALK,
            service_category=ServiceCategory.TRANSFER,
            service_name="JPO Lenteng Agung",
            avg_duration_min=2.5,
            fare=0,
            fare_product_id=None,
            data_confidence=DataConfidence.COMMUNITY,
            last_verified_at=date(2026, 7, 22),
            color="A78BFA",
            coordinates=coordinates,
            from_stop_name=str(graph.nodes[from_id].get("name") or from_id),
            to_stop_name=str(graph.nodes[to_id].get("name") or to_id),
            from_stop_lat=coordinates[0][1],
            from_stop_lng=coordinates[0][0],
            to_stop_lat=coordinates[-1][1],
            to_stop_lng=coordinates[-1][0],
            distance_meters=_geometry_distance_meters(coordinates),
            instruction=instruction,
            walking_route_source=WalkingRouteSource.CURATED,
        )
        graph.add_edge(
            segment.from_stop_id,
            segment.to_stop_id,
            key=segment.id,
            segment=segment,
        )


def _prune_ui_barrier_shortcuts(graph: nx.MultiDiGraph) -> None:
    """Force east/west walking across the railway through the reviewed gate edge."""
    west_nodes = {UI_KRL_STOP_ID, "bikun:stasiun-ui"}
    removals: set[tuple[str, str, str]] = set()
    for node_id in west_nodes:
        if node_id not in graph:
            continue
        for source, target, key, data in graph.out_edges(node_id, keys=True, data=True):
            segment = data.get("segment")
            target_lng = graph.nodes[target].get("lng")
            if (
                segment is not None
                and segment.mode is TransportMode.WALK
                and target != UI_EAST_GATE_ID
                and target_lng is not None
                and float(target_lng) > UI_TRACK_BARRIER_LNG
            ):
                removals.add((source, target, key))
        for source, target, key, data in graph.in_edges(node_id, keys=True, data=True):
            segment = data.get("segment")
            source_lng = graph.nodes[source].get("lng")
            if (
                segment is not None
                and segment.mode is TransportMode.WALK
                and source != UI_EAST_GATE_ID
                and source_lng is not None
                and float(source_lng) > UI_TRACK_BARRIER_LNG
            ):
                removals.add((source, target, key))
    graph.remove_edges_from(removals)


def nearby_endpoint_access_nodes(
    graph: nx.MultiDiGraph,
    *,
    lat: float,
    lng: float,
    radius_meters: int,
) -> list[NearbyStop]:
    result = []
    for node_id, data in graph.nodes(data=True):
        if not data.get("endpoint_access"):
            continue
        distance = distance_meters(lat, lng, float(data["lat"]), float(data["lng"]))
        if distance <= radius_meters:
            result.append(
                NearbyStop(
                    id=node_id,
                    name=str(data["name"]),
                    lat=float(data["lat"]),
                    lng=float(data["lng"]),
                    modes=[TransportMode.WALK],
                    distance_meters=distance,
                    can_board=True,
                    can_alight=True,
                )
            )
    return sorted(result, key=lambda item: item.distance_meters)


def add_walking_pair(
    graph: nx.MultiDiGraph,
    first_id: str,
    second_id: str,
    first: tuple[float, float],
    second: tuple[float, float],
    identity: str,
    *,
    curated: bool = False,
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
            walking_distance_meters=distance if curated else None,
            distance_meters=distance if curated else None,
            walking_route_source=WalkingRouteSource.CURATED if curated else None,
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


def _geometry_distance_meters(coordinates: list[tuple[float, float]]) -> float:
    return sum(
        distance_meters(first[1], first[0], second[1], second[0])
        for first, second in zip(coordinates, coordinates[1:], strict=False)
    )


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
