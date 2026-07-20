"""Normalize the official TransJakarta GTFS schedule into routing data."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from statistics import mean
from typing import Any

from app.models.schema import DataConfidence, Segment, Stop, TransportMode

DEFAULT_COLOR = "009999"
DEFAULT_FARE = 3500


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
    fare_attributes: Any,
    fare_rules: Any,
    verified_at: date,
) -> TransitDataset:
    """Convert GTFS tables to validated domain models without touching the database."""
    stop_rows = {row["stop_id"]: row for row in stops.to_dict("records")}
    route_rows = {row["route_id"]: row for row in routes.to_dict("records")}
    trip_rows = {row["trip_id"]: row for row in trips.to_dict("records")}
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
    ordered_stop_times = stop_times.sort_values(["trip_id", "stop_sequence"])
    for trip_id, trip_stop_times in ordered_stop_times.groupby("trip_id"):
        trip = trip_rows.get(trip_id)
        if trip is None:
            continue
        route_id = trip["route_id"]
        direction_id = str(trip.get("direction_id") or "0")
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
                durations[(route_id, direction_id, from_stop_id, to_stop_id)].append(duration)

    segments = [
        _build_segment(
            route_id=route_id,
            direction_id=direction_id,
            from_stop=stop_rows[from_stop_id],
            to_stop=stop_rows[to_stop_id],
            avg_duration_min=mean(values),
            fare=route_fares.get(route_id, DEFAULT_FARE),
            color=_route_color(route_rows.get(route_id, {})),
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
    verified_at: date,
) -> Segment:
    from_stop_id = from_stop["stop_id"]
    to_stop_id = to_stop["stop_id"]
    return Segment(
        id=f"transjakarta:{route_id}:{direction_id}:{from_stop_id}:{to_stop_id}",
        route_id=f"transjakarta:{route_id}:{direction_id}",
        from_stop_id=f"transjakarta:{from_stop_id}",
        to_stop_id=f"transjakarta:{to_stop_id}",
        mode=TransportMode.TRANSJAKARTA,
        avg_duration_min=avg_duration_min,
        fare=fare,
        data_confidence=DataConfidence.OFFICIAL,
        last_verified_at=verified_at,
        color=color,
        coordinates=[
            (float(from_stop["stop_lon"]), float(from_stop["stop_lat"])),
            (float(to_stop["stop_lon"]), float(to_stop["stop_lat"])),
        ],
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
