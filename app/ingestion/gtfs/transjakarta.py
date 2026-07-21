"""Normalize the official TransJakarta GTFS schedule into routing data."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from math import isfinite
from pathlib import Path
from statistics import mean
from typing import Any

from app.models.schema import DataConfidence, Segment, ServiceCategory, Stop, TransportMode

DEFAULT_COLOR = "009999"
DEFAULT_FARE = 3500
SERVICE_CATEGORY_BY_ROUTE_DESC = {
    "BRT": ServiceCategory.MAIN,
    "Angkutan Umum Integrasi": ServiceCategory.FEEDER,
    "Rusun": ServiceCategory.FEEDER,
    "Mikrotrans": ServiceCategory.MICROTRANS,
    "Transjabodetabek": ServiceCategory.REGIONAL,
    "Royaltrans": ServiceCategory.PREMIUM,
    "Shuttle": ServiceCategory.SHUTTLE,
    "Bus Wisata": ServiceCategory.TOURIST,
}


@dataclass(frozen=True)
class TransitDataset:
    stops: list[Stop]
    segments: list[Segment]


def read_feed(path: Path, verified_at: date | None = None) -> TransitDataset:
    """Read a GTFS zip with gtfs-kit and return the TransJakarta routing graph data."""
    import gtfs_kit as gk

    feed = gk.read_feed(str(path), dist_units="km")
    return normalize_feed(
        stops=feed.stops,
        routes=feed.routes,
        trips=feed.trips,
        stop_times=feed.stop_times,
        shapes=feed.shapes,
        fare_attributes=feed.fare_attributes,
        fare_rules=feed.fare_rules,
        verified_at=verified_at or date.today(),
    )


def normalize_feed(
    *,
    stops: Any,
    routes: Any,
    trips: Any,
    stop_times: Any,
    shapes: Any,
    fare_attributes: Any,
    fare_rules: Any,
    verified_at: date,
) -> TransitDataset:
    """Convert GTFS tables to validated domain models without touching the database."""
    stop_rows = {row["stop_id"]: row for row in stops.to_dict("records")}
    route_rows = {row["route_id"]: row for row in routes.to_dict("records")}
    trip_rows = {row["trip_id"]: row for row in trips.to_dict("records")}
    shape_points = _shape_points(shapes)
    fares = {row["fare_id"]: int(float(row["price"])) for row in fare_attributes.to_dict("records")}
    route_fares = {
        row["route_id"]: fares[row["fare_id"]]
        for row in fare_rules.to_dict("records")
        if row.get("route_id") and row.get("fare_id") in fares
    }

    normalized_stops = [
        Stop(
            id=f"transjakarta:{row['stop_id']}",
            name=row["stop_name"],
            lat=float(row["stop_lat"]),
            lng=float(row["stop_lon"]),
            modes=[TransportMode.TRANSJAKARTA],
        )
        for row in stop_rows.values()
        if row.get("stop_lat") and row.get("stop_lon")
    ]

    durations: dict[tuple[str, str, str, str], list[float]] = defaultdict(list)
    geometries: dict[tuple[str, str, str, str], list[tuple[float, float]]] = {}
    ordered_stop_times = stop_times.sort_values(["trip_id", "stop_sequence"])
    for trip_id, trip_stop_times in ordered_stop_times.groupby("trip_id"):
        trip = trip_rows.get(trip_id)
        if trip is None:
            continue
        route_id = trip["route_id"]
        direction_id = str(trip.get("direction_id") or "0")
        trip_shape = shape_points.get(trip.get("shape_id"), [])
        times = trip_stop_times.to_dict("records")
        for previous, current in zip(times, times[1:], strict=False):
            duration = _duration_minutes(
                previous.get("departure_time"), current.get("arrival_time")
            )
            if duration is None:
                continue
            from_stop_id = previous["stop_id"]
            to_stop_id = current["stop_id"]
            if from_stop_id in stop_rows and to_stop_id in stop_rows:
                key = (route_id, direction_id, from_stop_id, to_stop_id)
                durations[key].append(duration)
                geometries.setdefault(
                    key,
                    _segment_coordinates(
                        trip_shape,
                        previous.get("shape_dist_traveled"),
                        current.get("shape_dist_traveled"),
                        stop_rows[from_stop_id],
                        stop_rows[to_stop_id],
                    ),
                )

    segments = [
        _build_segment(
            route_id=route_id,
            direction_id=direction_id,
            from_stop=stop_rows[from_stop_id],
            to_stop=stop_rows[to_stop_id],
            avg_duration_min=mean(values),
            fare=route_fares.get(route_id, DEFAULT_FARE),
            color=_route_color(route_rows.get(route_id, {})),
            service_name=_service_name(route_rows.get(route_id, {})),
            route_code=_route_code(route_rows.get(route_id, {})),
            route_name=_route_name(route_rows.get(route_id, {})),
            coordinates=geometries[(route_id, direction_id, from_stop_id, to_stop_id)],
            verified_at=verified_at,
        )
        for (route_id, direction_id, from_stop_id, to_stop_id), values in durations.items()
    ]
    return TransitDataset(stops=normalized_stops, segments=segments)


def _build_segment(
    *,
    route_id: str,
    direction_id: str,
    from_stop: dict[str, Any],
    to_stop: dict[str, Any],
    avg_duration_min: float,
    fare: int,
    color: str,
    service_name: str,
    route_code: str,
    route_name: str,
    coordinates: list[tuple[float, float]],
    verified_at: date,
) -> Segment:
    from_stop_id = from_stop["stop_id"]
    to_stop_id = to_stop["stop_id"]
    return Segment(
        id=f"transjakarta:{route_id}:{direction_id}:{from_stop_id}:{to_stop_id}",
        route_id=f"transjakarta:{route_id}:{direction_id}",
        route_code=route_code,
        route_name=route_name,
        from_stop_id=f"transjakarta:{from_stop_id}",
        to_stop_id=f"transjakarta:{to_stop_id}",
        mode=TransportMode.TRANSJAKARTA,
        service_category=_service_category(service_name),
        service_name=service_name,
        avg_duration_min=avg_duration_min,
        fare=fare,
        fare_product_id="transjakarta:regular",
        data_confidence=DataConfidence.OFFICIAL,
        last_verified_at=verified_at,
        color=color,
        coordinates=coordinates,
    )


def _duration_minutes(departure_time: str | None, arrival_time: str | None) -> float | None:
    if not departure_time or not arrival_time:
        return None
    departure_seconds = _seconds_since_service_day_start(departure_time)
    arrival_seconds = _seconds_since_service_day_start(arrival_time)
    duration = (arrival_seconds - departure_seconds) / 60
    return duration if duration > 0 else None


def _seconds_since_service_day_start(value: str) -> int:
    hours, minutes, seconds = (int(part) for part in value.split(":", maxsplit=2))
    return hours * 3600 + minutes * 60 + seconds


def _route_color(route: dict[str, Any]) -> str:
    color = str(route.get("route_color") or DEFAULT_COLOR).upper()
    if len(color) == 6 and all(character in "0123456789ABCDEF" for character in color):
        return color
    return DEFAULT_COLOR


def _service_name(route: dict[str, Any]) -> str:
    service_name = str(route.get("route_desc") or "").strip()
    if service_name not in SERVICE_CATEGORY_BY_ROUTE_DESC:
        route_id = route.get("route_id", "unknown")
        raise ValueError(
            f"unsupported TransJakarta route_desc {service_name!r} for route {route_id}"
        )
    return service_name


def _route_code(route: dict[str, Any]) -> str:
    return str(route.get("route_short_name") or route.get("route_id") or "?").strip()


def _route_name(route: dict[str, Any]) -> str:
    code = _route_code(route)
    long_name = str(route.get("route_long_name") or "").strip()
    return long_name or f"TransJakarta {code}"


def _service_category(service_name: str) -> ServiceCategory:
    return SERVICE_CATEGORY_BY_ROUTE_DESC[service_name]


def _shape_points(shapes: Any) -> dict[str, list[tuple[float, float, float]]]:
    if shapes is None:
        return {}
    points: dict[str, list[tuple[float, float, float]]] = defaultdict(list)
    ordered = shapes.sort_values(["shape_id", "shape_pt_sequence"])
    for row in ordered.to_dict("records"):
        distance = _finite_float(row.get("shape_dist_traveled"))
        if distance is None:
            continue
        points[row["shape_id"]].append(
            (distance, float(row["shape_pt_lon"]), float(row["shape_pt_lat"]))
        )
    return dict(points)


def _segment_coordinates(
    shape: list[tuple[float, float, float]],
    start_distance: object,
    end_distance: object,
    from_stop: dict[str, Any],
    to_stop: dict[str, Any],
) -> list[tuple[float, float]]:
    start = _finite_float(start_distance)
    end = _finite_float(end_distance)
    endpoints = [
        (float(from_stop["stop_lon"]), float(from_stop["stop_lat"])),
        (float(to_stop["stop_lon"]), float(to_stop["stop_lat"])),
    ]
    if start is None or end is None or end <= start:
        return endpoints
    between = [(lng, lat) for distance, lng, lat in shape if start < distance < end]
    return [endpoints[0], *between, endpoints[1]]


def _finite_float(value: object) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None
