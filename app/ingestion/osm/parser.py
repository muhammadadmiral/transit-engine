import re
import unicodedata
from datetime import date
from typing import Any
from math import asin, cos, radians, sin, sqrt

from app.models.schema import DataConfidence, Segment, ServiceCategory, Stop, TransportMode
from app.ingestion.gtfs.transjakarta import TransitDataset

VERIFIED_AT = date(2026, 7, 20)
VIRTUAL_STOP_INTERVAL_METERS = 800.0

def _normalize(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", normalized.casefold()).strip("-")

def _distance_meters(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    delta_lat = radians(lat2 - lat1)
    delta_lng = radians(lng2 - lng1)
    value = sin(delta_lat / 2) ** 2 + (
        cos(radians(lat1)) * cos(radians(lat2)) * sin(delta_lng / 2) ** 2
    )
    return 2 * 6_371_008.8 * asin(sqrt(value))

def parse_osm_relations(relations: list[dict[str, Any]]) -> TransitDataset:
    stops: dict[str, Stop] = {}
    segments: list[Segment] = []

    for relation in relations:
        tags = relation.get("tags", {})
        ref = tags.get("ref") or tags.get("name") or "Unknown"
        name = tags.get("name") or f"Angkot {ref}"
        
        # Build continuous geometry from members
        coordinates: list[tuple[float, float]] = []
        for member in relation.get("members", []):
            if member.get("type") == "way" and "geometry" in member:
                for pt in member["geometry"]:
                    coord = (float(pt["lon"]), float(pt["lat"]))
                    # prevent consecutive duplicates
                    if not coordinates or coordinates[-1] != coord:
                        coordinates.append(coord)
                        
        if len(coordinates) < 2:
            continue
            
        route_slug = _normalize(ref)
        rel_id = relation.get("id", "0")
        route_id = f"angkot:{route_slug}_{rel_id}"
        
        # Generate virtual stops along the route
        route_stops: list[tuple[str, tuple[float, float]]] = []
        
        # Always add the first point
        start_pt = coordinates[0]
        start_id = f"{route_id}:stop_0"
        route_stops.append((start_id, start_pt))
        stops[start_id] = Stop(
            id=start_id,
            name=f"Titik Awal {name}",
            lat=start_pt[1],
            lng=start_pt[0],
            modes=[TransportMode.ANGKOT],
        )
        
        distance_since_last_stop = 0.0
        last_stop_idx = 0
        
        for i in range(1, len(coordinates)):
            pt1 = coordinates[i-1]
            pt2 = coordinates[i]
            dist = _distance_meters(pt1[1], pt1[0], pt2[1], pt2[0])
            distance_since_last_stop += dist
            
            # If we traveled far enough, place a virtual stop
            if distance_since_last_stop >= VIRTUAL_STOP_INTERVAL_METERS and i < len(coordinates) - 1:
                stop_id = f"{route_id}:stop_{i}"
                route_stops.append((stop_id, pt2))
                stops[stop_id] = Stop(
                    id=stop_id,
                    name=f"Perhentian {name} (KM {round(len(route_stops) * 0.8, 1)})",
                    lat=pt2[1],
                    lng=pt2[0],
                    modes=[TransportMode.ANGKOT],
                )
                
                # Build segment from last stop to this stop
                sub_coords = coordinates[last_stop_idx:i+1]
                duration_min = round(max(1.0, distance_since_last_stop / 300.0), 1) # approx 18 km/h
                
                from_id = route_stops[-2][0]
                segments.append(
                    Segment(
                        id=f"{route_id}:seg_{last_stop_idx}_{i}",
                        route_id=route_id,
                        from_stop_id=from_id,
                        to_stop_id=stop_id,
                        mode=TransportMode.ANGKOT,
                        service_category=ServiceCategory.FEEDER,
                        service_name=name,
                        avg_duration_min=duration_min,
                        fare=5000,
                        fare_product_id="angkot:regular",
                        data_confidence=DataConfidence.COMMUNITY,
                        last_verified_at=VERIFIED_AT,
                        color="FF9800", # Orange for angkot
                        coordinates=sub_coords,
                    )
                )
                
                distance_since_last_stop = 0.0
                last_stop_idx = i
                
        # Add the final destination stop
        end_pt = coordinates[-1]
        end_id = f"{route_id}:stop_end"
        route_stops.append((end_id, end_pt))
        stops[end_id] = Stop(
            id=end_id,
            name=f"Tujuan {name}",
            lat=end_pt[1],
            lng=end_pt[0],
            modes=[TransportMode.ANGKOT],
        )
        
        # Build the final segment
        if last_stop_idx < len(coordinates) - 1:
            sub_coords = coordinates[last_stop_idx:]
            duration_min = round(max(1.0, distance_since_last_stop / 300.0), 1)
            segments.append(
                Segment(
                    id=f"{route_id}:seg_{last_stop_idx}_end",
                    route_id=route_id,
                    from_stop_id=route_stops[-2][0],
                    to_stop_id=end_id,
                    mode=TransportMode.ANGKOT,
                    service_category=ServiceCategory.FEEDER,
                    service_name=name,
                    avg_duration_min=duration_min,
                    fare=5000,
                    fare_product_id="angkot:regular",
                    data_confidence=DataConfidence.COMMUNITY,
                    last_verified_at=VERIFIED_AT,
                    color="FF9800",
                    coordinates=sub_coords,
                )
            )

    return TransitDataset(stops=list(stops.values()), segments=segments)
