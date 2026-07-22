"""Convert reviewed OpenStreetMap angkot relations into routing records."""

import re
import unicodedata
from datetime import date
from math import cos, hypot, radians
from typing import Any

from app.models.schema import DataConfidence, FlexibleRoute, ServiceCategory, TransportMode

MAX_ROUTE_SLUG_LENGTH = 40
MAX_MEMBER_GAP_METERS = 180
MIN_CONNECTED_MEMBER_RATIO = 0.95
ANGKOT_KEYWORDS = ("angkot", "angkutan kota", "koasi", "kwk", "mikrolet")
EXCLUDED_NETWORK_KEYWORDS = (
    "transjakarta",
    "transjabodetabek",
    "mikrotrans",
    "jaklingko",
    "royaltrans",
    "biskita",
    "teman bus",
    "trans tangerang",
)
LOCAL_ROUTE_REF = re.compile(r"^(?:D|K|A|B|C|E|F)[ .-]?\d{1,3}[A-Z]?$", re.IGNORECASE)


def parse_osm_relations(
    relations: list[dict[str, Any]], *, verified_at: date | None = None
) -> list[FlexibleRoute]:
    routes: list[FlexibleRoute] = []
    seen_relation_ids: set[str] = set()
    verification_date = verified_at or date.today()

    for relation in relations:
        tags = relation.get("tags", {})
        relation_id = str(relation.get("id", ""))
        if not relation_id or relation_id in seen_relation_ids or not _is_angkot_relation(tags):
            continue
        seen_relation_ids.add(relation_id)

        coordinates = _relation_coordinates(relation)
        if len(coordinates) < 2:
            continue

        reference = str(tags.get("ref") or tags.get("name") or relation_id)
        name = str(tags.get("name") or f"Angkot {reference}")
        route_code = _display_route_code(reference, name)
        route_slug = _normalize(reference)[:MAX_ROUTE_SLUG_LENGTH] or "route"
        route_id = f"angkot:osm:{relation_id}:{route_slug}"
        routes.append(
            FlexibleRoute(
                id=route_id,
                route_code=route_code,
                route_name=name,
                mode=TransportMode.ANGKOT,
                service_category=ServiceCategory.FEEDER,
                service_name=name,
                avg_speed_kmh=18,
                fare=5000,
                fare_product_id="angkot:regular",
                data_confidence=DataConfidence.COMMUNITY,
                last_verified_at=verification_date,
                color="FF9800",
                coordinates=coordinates,
                source_url=f"https://www.openstreetmap.org/relation/{relation_id}",
            )
        )

    # Many community relations map only one direction even though conventional
    # angkot operates PP. Preserve explicitly mapped opposite directions; only
    # synthesize the return direction for a singleton, non-loop corridor.
    routes_by_code: dict[str, list[FlexibleRoute]] = {}
    for route in routes:
        routes_by_code.setdefault(route.route_code.casefold(), []).append(route)
    reverse_routes = []
    for siblings in routes_by_code.values():
        if len(siblings) != 1:
            continue
        route = siblings[0]
        if _coordinate_distance(route.coordinates[0], route.coordinates[-1]) < 0.00001:
            continue
        reverse_routes.append(
            route.model_copy(
                update={
                    "id": f"{route.id}:reverse",
                    "route_name": f"{route.route_name} (arah balik)",
                    "coordinates": list(reversed(route.coordinates)),
                }
            )
        )
    return [*routes, *reverse_routes]


def _is_angkot_relation(tags: dict[str, Any]) -> bool:
    route_type = str(tags.get("route", "")).casefold()
    if route_type in {"share_taxi", "minibus"}:
        return True
    if route_type != "bus":
        return False
    description = " ".join(
        str(tags.get(key, "")).casefold() for key in ("name", "operator", "network", "description")
    )
    if any(keyword in description for keyword in EXCLUDED_NETWORK_KEYWORDS):
        return False
    reference = str(tags.get("ref", "")).strip()
    return (
        any(keyword in description for keyword in ANGKOT_KEYWORDS)
        or bool(LOCAL_ROUTE_REF.fullmatch(reference))
        or "trayek" in description
    )


def _relation_coordinates(relation: dict[str, Any]) -> list[tuple[float, float]]:
    lines: list[list[tuple[float, float]]] = []
    for member in relation.get("members", []):
        if member.get("type") != "way" or not member.get("geometry"):
            continue
        line = [(float(point["lon"]), float(point["lat"])) for point in member["geometry"]]
        if len(line) < 2:
            continue
        lines.append(line)
    if not lines:
        return []

    # OSM route members are frequently uploaded out of order. Concatenating
    # that raw order creates kilometre-long straight lines in the client.
    best_coordinates: list[tuple[float, float]] = []
    best_used = 0
    for seed_index in range(len(lines)):
        for reverse_seed in (False, True):
            coordinates, used = _connected_chain(lines, seed_index, reverse_seed)
            if used > best_used or (used == best_used and len(coordinates) > len(best_coordinates)):
                best_coordinates = coordinates
                best_used = used
    if best_used / len(lines) < MIN_CONNECTED_MEMBER_RATIO:
        return []
    return best_coordinates


def _connected_chain(
    lines: list[list[tuple[float, float]]], seed_index: int, reverse_seed: bool
) -> tuple[list[tuple[float, float]], int]:
    seed = list(reversed(lines[seed_index])) if reverse_seed else list(lines[seed_index])
    coordinates = seed
    remaining = {index for index in range(len(lines)) if index != seed_index}
    used = 1
    while remaining:
        candidates: list[tuple[float, int, str, bool]] = []
        for index in remaining:
            line = lines[index]
            candidates.extend(
                (
                    (_gap_meters(coordinates[-1], line[0]), index, "append", False),
                    (_gap_meters(coordinates[-1], line[-1]), index, "append", True),
                    (_gap_meters(coordinates[0], line[-1]), index, "prepend", False),
                    (_gap_meters(coordinates[0], line[0]), index, "prepend", True),
                )
            )
        gap, index, side, reverse = min(candidates)
        if gap > MAX_MEMBER_GAP_METERS:
            break
        line = list(reversed(lines[index])) if reverse else list(lines[index])
        if side == "append":
            coordinates.extend(line[1:] if coordinates[-1] == line[0] else line)
        else:
            coordinates = [
                *(line[:-1] if line[-1] == coordinates[0] else line),
                *coordinates,
            ]
        remaining.remove(index)
        used += 1
    return coordinates, used


def _gap_meters(first: tuple[float, float], second: tuple[float, float]) -> float:
    mean_latitude = radians((first[1] + second[1]) / 2)
    return hypot(
        (first[0] - second[0]) * 111_320 * cos(mean_latitude),
        (first[1] - second[1]) * 110_574,
    )


def _normalize(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", normalized.casefold()).strip("-")


def _display_route_code(reference: str, name: str) -> str:
    if len(reference) <= 16:
        return reference.upper()
    match = re.search(r"\b([A-Z]{0,2}\d{1,3}[A-Z]?)\b", name.upper())
    return match.group(1) if match else "ANGKOT"


def _coordinate_distance(first: tuple[float, float], second: tuple[float, float]) -> float:
    # Sufficient for orienting adjacent OSM members; no routing distance is inferred here.
    return (first[0] - second[0]) ** 2 + (first[1] - second[1]) ** 2
