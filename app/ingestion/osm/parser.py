"""Convert reviewed OpenStreetMap angkot relations into routing records."""

import re
import unicodedata
from datetime import date
from math import asin, cos, radians, sin, sqrt
from typing import Any

from app.ingestion.gtfs.transjakarta import TransitDataset
from app.models.schema import DataConfidence, Segment, ServiceCategory, Stop, TransportMode

VIRTUAL_STOP_INTERVAL_METERS = 800.0
MAX_ROUTE_SLUG_LENGTH = 40
ANGKOT_KEYWORDS = ("angkot", "angkutan kota", "koasi", "kwk", "mikrolet")


def parse_osm_relations(
    relations: list[dict[str, Any]], *, verified_at: date | None = None
) -> TransitDataset:
    stops: dict[str, Stop] = {}
    segments: list[Segment] = []
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
        route_slug = _normalize(reference)[:MAX_ROUTE_SLUG_LENGTH] or "route"
        route_id = f"angkot:osm:{relation_id}:{route_slug}"
        route_stops: list[tuple[str, tuple[float, float]]] = []

        start_point = coordinates[0]
        start_id = f"{route_id}:s0"
        route_stops.append((start_id, start_point))
        stops[start_id] = _stop(start_id, f"Titik awal {name}", start_point)

        distance_since_stop = 0.0
        last_stop_index = 0
        stop_number = 1
        for index, (previous, point) in enumerate(
            zip(coordinates, coordinates[1:], strict=False), start=1
        ):
            distance_since_stop += _distance_meters(previous[1], previous[0], point[1], point[0])
            if distance_since_stop < VIRTUAL_STOP_INTERVAL_METERS or index == len(coordinates) - 1:
                continue

            stop_id = f"{route_id}:s{stop_number}"
            stops[stop_id] = _stop(stop_id, f"Perhentian {stop_number} — {name}", point)
            route_stops.append((stop_id, point))
            segments.append(
                _segment(
                    route_id,
                    stop_number - 1,
                    route_stops[-2][0],
                    stop_id,
                    name,
                    coordinates[last_stop_index : index + 1],
                    distance_since_stop,
                    verification_date,
                )
            )
            stop_number += 1
            last_stop_index = index
            distance_since_stop = 0.0

        end_point = coordinates[-1]
        end_id = f"{route_id}:send"
        stops[end_id] = _stop(end_id, f"Tujuan {name}", end_point)
        route_stops.append((end_id, end_point))
        segments.append(
            _segment(
                route_id,
                stop_number - 1,
                route_stops[-2][0],
                end_id,
                name,
                coordinates[last_stop_index:],
                distance_since_stop,
                verification_date,
            )
        )

    return TransitDataset(stops=list(stops.values()), segments=segments)


def _is_angkot_relation(tags: dict[str, Any]) -> bool:
    route_type = str(tags.get("route", "")).casefold()
    if route_type in {"share_taxi", "minibus"}:
        return True
    if route_type != "bus":
        return False
    description = " ".join(
        str(tags.get(key, "")).casefold() for key in ("name", "operator", "network", "description")
    )
    return any(keyword in description for keyword in ANGKOT_KEYWORDS)


def _relation_coordinates(relation: dict[str, Any]) -> list[tuple[float, float]]:
    coordinates: list[tuple[float, float]] = []
    for member in relation.get("members", []):
        if member.get("type") != "way" or not member.get("geometry"):
            continue
        line = [(float(point["lon"]), float(point["lat"])) for point in member["geometry"]]
        if len(line) < 2:
            continue
        if coordinates and _coordinate_distance(coordinates[-1], line[-1]) < _coordinate_distance(
            coordinates[-1], line[0]
        ):
            line.reverse()
        if coordinates and coordinates[-1] == line[0]:
            line = line[1:]
        coordinates.extend(line)
    return coordinates


def _stop(stop_id: str, name: str, point: tuple[float, float]) -> Stop:
    return Stop(
        id=stop_id,
        name=name,
        lat=point[1],
        lng=point[0],
        modes=[TransportMode.ANGKOT],
    )


def _segment(
    route_id: str,
    number: int,
    from_stop_id: str,
    to_stop_id: str,
    name: str,
    coordinates: list[tuple[float, float]],
    distance_meters: float,
    verified_at: date,
) -> Segment:
    return Segment(
        id=f"{route_id}:g{number}",
        route_id=route_id,
        from_stop_id=from_stop_id,
        to_stop_id=to_stop_id,
        mode=TransportMode.ANGKOT,
        service_category=ServiceCategory.FEEDER,
        service_name=name,
        avg_duration_min=round(max(1.0, distance_meters / 300.0), 1),
        fare=5000,
        fare_product_id="angkot:regular",
        data_confidence=DataConfidence.COMMUNITY,
        last_verified_at=verified_at,
        color="FF9800",
        coordinates=coordinates,
    )


def _normalize(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", normalized.casefold()).strip("-")


def _coordinate_distance(first: tuple[float, float], second: tuple[float, float]) -> float:
    return _distance_meters(first[1], first[0], second[1], second[0])


def _distance_meters(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    delta_lat = radians(lat2 - lat1)
    delta_lng = radians(lng2 - lng1)
    value = sin(delta_lat / 2) ** 2 + (
        cos(radians(lat1)) * cos(radians(lat2)) * sin(delta_lng / 2) ** 2
    )
    return 2 * 6_371_008.8 * asin(sqrt(value))
