"""Generate compact per-segment rail geometry from downloaded OSM snapshots.

This is a maintainer tool, not part of application startup. Raw OSM responses
stay outside the repository; only the compact attributed snapshot is shipped.
"""

import argparse
import json
import re
import unicodedata
from pathlib import Path
from typing import Any

import networkx as nx

from app.ingestion.curated.krl import KRL_STATIONS
from app.ingestion.curated.rail import (
    LRT_JABODEBEK_BEKASI_STATIONS,
    LRT_JABODEBEK_CIBUBUR_STATIONS,
    LRT_JABODEBEK_COMMON_STATIONS,
    LRT_JAKARTA_STATIONS,
    MRT_STATIONS,
)

Point = tuple[float, float]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", type=Path, default=Path("/private/tmp"))
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).with_name("data") / "rail_geometries.json",
    )
    args = parser.parse_args()

    segments: dict[str, list[Point]] = {}
    _add_curated_relation(
        segments,
        args.source_dir / "osm-precise-mrt.json",
        "mrt:north-south",
        "mrt",
        MRT_STATIONS,
    )
    _add_curated_relation(
        segments,
        args.source_dir / "osm-precise-lrt-jakarta.json",
        "lrt-jakarta:line-1",
        "lrt-jakarta",
        LRT_JAKARTA_STATIONS,
    )

    krl_sources = (
        ("osm-krl-bogor.json", "krl:bogor-line"),
        ("osm-krl-nambo.json", "krl:bogor-line"),
        ("osm-krl-rangkasbitung.json", "krl:rangkasbitung-line"),
        ("osm-krl-tangerang.json", "krl:tangerang-line"),
        ("osm-krl-tanjung-priok.json", "krl:tanjung-priok-line"),
        ("osm-krl-cikarang.json", "krl:cikarang-loop-line"),
        ("osm-krl-cikarang-pasar-senen.json", "krl:cikarang-loop-line"),
    )
    for filename, route_id in krl_sources:
        _add_relation_with_member_stops(
            segments,
            args.source_dir / filename,
            route_id,
            "krl",
            _krl_name_to_slug(),
        )

    _add_lrt_jabodebek(
        segments,
        args.source_dir / "lrt-nominatim.json",
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            {
                "license": "OpenStreetMap contributors, ODbL 1.0",
                "sourceUrl": "https://www.openstreetmap.org/copyright",
                "verifiedAt": "2026-07-20",
                "segments": segments,
            },
            separators=(",", ":"),
        )
        + "\n"
    )
    print(f"Wrote {len(segments)} precise directed rail geometries to {args.output}.")


def _add_curated_relation(
    output: dict[str, list[Point]],
    path: Path,
    route_id: str,
    namespace: str,
    stations: tuple[tuple[str, str, float, float], ...],
) -> None:
    payload = json.loads(path.read_text())
    line = _relation_line(payload)
    station_points = [(station_id, (lng, lat)) for station_id, _, lat, lng in stations]
    _store_cuts(output, route_id, namespace, line, station_points)


def _add_relation_with_member_stops(
    output: dict[str, list[Point]],
    path: Path,
    route_id: str,
    namespace: str,
    name_to_slug: dict[str, str],
) -> None:
    payload = json.loads(path.read_text())
    relation = next(item for item in payload["elements"] if item["type"] == "relation")
    elements = {(item["type"], item["id"]): item for item in payload["elements"]}
    station_points = []
    for member in relation["members"]:
        if not member.get("role", "").startswith("stop"):
            continue
        node = elements.get((member["type"], member["ref"]))
        if not node or "lat" not in node:
            continue
        normalized_name = _normalize(node.get("tags", {}).get("name", ""))
        slug = name_to_slug.get(normalized_name)
        if slug:
            station_points.append((slug, (node["lon"], node["lat"])))
    _store_cuts(output, route_id, namespace, _relation_line(payload), station_points)


def _relation_line(payload: dict[str, Any]) -> list[Point]:
    relation = next(item for item in payload["elements"] if item["type"] == "relation")
    elements = {(item["type"], item["id"]): item for item in payload["elements"]}
    nodes = {
        item["id"]: (item["lon"], item["lat"])
        for item in payload["elements"]
        if item["type"] == "node"
    }
    line: list[Point] = []
    for member in relation["members"]:
        way = elements.get(("way", member["ref"])) if member["type"] == "way" else None
        if not way:
            continue
        coordinates = [nodes[node_id] for node_id in way["nodes"]]
        if not line:
            line.extend(coordinates)
            continue
        if _squared_distance(line[-1], coordinates[-1]) < _squared_distance(
            line[-1], coordinates[0]
        ):
            coordinates.reverse()
        if line[-1] == coordinates[0]:
            line.extend(coordinates[1:])
        else:
            line.extend(coordinates)
    return line


def _store_cuts(
    output: dict[str, list[Point]],
    route_id: str,
    namespace: str,
    line: list[Point],
    station_points: list[tuple[str, Point]],
) -> None:
    if len(station_points) < 2:
        raise ValueError(f"Not enough stations for {route_id}")
    if _nearest_index(line, station_points[0][1]) > _nearest_index(line, station_points[-1][1]):
        line.reverse()

    indexes = []
    search_start = 0
    for _, point in station_points:
        index = _nearest_index(line, point, search_start)
        indexes.append(index)
        search_start = index

    for (from_slug, from_point), (to_slug, to_point), start, end in zip(
        station_points, station_points[1:], indexes, indexes[1:], strict=False
    ):
        coordinates = _dedupe([from_point, *line[start : end + 1], to_point])
        output[_key(route_id, namespace, from_slug, to_slug)] = coordinates


def _add_lrt_jabodebek(output: dict[str, list[Point]], path: Path) -> None:
    payload = json.loads(path.read_text())
    graph: nx.Graph = nx.Graph()
    for item in payload:
        geometry = item.get("geojson", {})
        if geometry.get("type") != "LineString":
            continue
        coordinates = [tuple(point) for point in geometry["coordinates"]]
        for first, second in zip(coordinates, coordinates[1:], strict=False):
            graph.add_edge(first, second, weight=_squared_distance(first, second) ** 0.5)
    _connect_components(graph)

    routes = (
        (
            "lrt-jabodebek:bekasi",
            (*LRT_JABODEBEK_COMMON_STATIONS, *LRT_JABODEBEK_BEKASI_STATIONS),
        ),
        (
            "lrt-jabodebek:cibubur",
            (*LRT_JABODEBEK_COMMON_STATIONS, *LRT_JABODEBEK_CIBUBUR_STATIONS),
        ),
    )
    graph_points = list(graph.nodes)
    for route_id, stations in routes:
        for first, second in zip(stations, stations[1:], strict=False):
            from_slug, _, from_lat, from_lng = first
            to_slug, _, to_lat, to_lng = second
            from_point = (from_lng, from_lat)
            to_point = (to_lng, to_lat)
            from_node = min(graph_points, key=lambda point: _squared_distance(point, from_point))
            to_node = min(graph_points, key=lambda point: _squared_distance(point, to_point))
            path_points = nx.shortest_path(graph, from_node, to_node, weight="weight")
            coordinates = _dedupe([from_point, *path_points, to_point])
            output[_key(route_id, "lrt-jabodebek", from_slug, to_slug)] = coordinates


def _connect_components(graph: nx.Graph) -> None:
    """Bridge tiny gaps between separately mapped OSM ways using their nearest endpoints."""
    while not nx.is_connected(graph):
        components = [list(component) for component in nx.connected_components(graph)]
        _, first, second = min(
            (
                (_squared_distance(first, second), first, second)
                for index, component in enumerate(components)
                for other in components[index + 1 :]
                for first in component
                for second in other
            ),
            key=lambda candidate: candidate[0],
        )
        graph.add_edge(first, second, weight=_squared_distance(first, second) ** 0.5)


def _krl_name_to_slug() -> dict[str, str]:
    result = {_normalize(name): slug for slug, (name, _, _) in KRL_STATIONS.items()}
    result[_normalize("Tanjung Priuk")] = "tanjung-priok"
    result[_normalize("Parungpanjang")] = "parung-panjang"
    return result


def _normalize(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", normalized.casefold()).strip()


def _nearest_index(line: list[Point], target: Point, start: int = 0) -> int:
    return min(range(start, len(line)), key=lambda index: _squared_distance(line[index], target))


def _squared_distance(first: Point, second: Point) -> float:
    return (first[0] - second[0]) ** 2 + (first[1] - second[1]) ** 2


def _dedupe(points: list[Point]) -> list[Point]:
    return [point for index, point in enumerate(points) if index == 0 or point != points[index - 1]]


def _key(route_id: str, namespace: str, from_slug: str, to_slug: str) -> str:
    return f"{route_id}|{namespace}:{from_slug}|{namespace}:{to_slug}"


if __name__ == "__main__":
    main()
