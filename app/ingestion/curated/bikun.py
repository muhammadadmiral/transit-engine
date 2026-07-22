"""Reviewed Bikun UI stops and road-following geometry from OSM route relations."""

import json
import re
import unicodedata
from datetime import date
from math import asin, cos, radians, sin, sqrt
from pathlib import Path

from app.ingestion.gtfs.transjakarta import TransitDataset
from app.models.schema import DataConfidence, Segment, ServiceCategory, Stop, TransportMode

VERIFIED_AT = date(2025, 1, 10)
AVERAGE_SPEED_KMH = 18.0
DWELL_MIN = 0.35
DATA_PATH = Path(__file__).with_name("data") / "bikun_routes.json"

_SLUG_OVERRIDES = {
    "Asrama UI": "asrama",
    "Resimen Mahasiswa": "menwa",
    "Stasiun KRL Universitas Indonesia": "stasiun-ui",
    "Fakultas Psikologi": "psikologi",
    "Fakultas Ilmu Sosial dan Ilmu Politik": "fisip",
    "Fakultas Ilmu Pengetahuan Budaya": "fib",
    "Fakultas Ekonomi dan Bisnis": "feb",
    "Fakultas Teknik": "teknik",
    "Program Vokasi": "vokasi",
    "Pusgiwa": "pusgiwa",
    "Fakultas Matematika dan IPA": "mipa",
    "Fakultas Ilmu Keperawatan": "fik",
    "Fakultas Kesehatan Masyarakat": "fkm",
    "Rumpun Ilmu Kesehatan": "rik",
    "Balairung": "balairung",
    "Masjid UI": "masjid-ui",
    "Fakultas Hukum": "hukum",
    "Pondok Cina": "pondok-cina",
    "SOR": "sor",
}


def build_bikun_dataset() -> TransitDataset:
    data = json.loads(DATA_PATH.read_text())
    stops: dict[str, Stop] = {}
    segments: list[Segment] = []

    for route_key in ("red", "blue"):
        route = data[route_key]
        rows = route["stops"]
        for row in rows:
            slug = _stop_slug(row["name"])
            stops.setdefault(
                slug,
                Stop(
                    id=f"bikun:{slug}",
                    name=f"Halte Bikun {row['name']}",
                    lat=float(row["lat"]),
                    lng=float(row["lng"]),
                    modes=[TransportMode.BIKUN],
                ),
            )

        for index, row in enumerate(rows):
            following = rows[(index + 1) % len(rows)]
            from_slug = _stop_slug(row["name"])
            to_slug = _stop_slug(following["name"])
            coordinates = [tuple(point) for point in row["geometry_to_next"]]
            distance_meters = _geometry_distance_meters(coordinates)
            segments.append(
                Segment(
                    id=f"bikun:{route_key}:{index}:{from_slug}:{to_slug}",
                    route_id=f"bikun:{route_key}",
                    route_code=route_key.upper(),
                    route_name=route["name"],
                    from_stop_id=f"bikun:{from_slug}",
                    to_stop_id=f"bikun:{to_slug}",
                    mode=TransportMode.BIKUN,
                    service_category=ServiceCategory.BIKUN,
                    service_name=route["name"],
                    avg_duration_min=round(
                        max(0.6, distance_meters / (AVERAGE_SPEED_KMH * 1000 / 60) + DWELL_MIN),
                        1,
                    ),
                    fare=0,
                    fare_product_id="bikun:regular",
                    data_confidence=DataConfidence.COMMUNITY,
                    last_verified_at=VERIFIED_AT,
                    color=route["color"],
                    coordinates=coordinates,
                )
            )

    return TransitDataset(stops=list(stops.values()), segments=segments)


def _stop_slug(name: str) -> str:
    if name in _SLUG_OVERRIDES:
        return _SLUG_OVERRIDES[name]
    normalized = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", normalized.casefold()).strip("-")


def _geometry_distance_meters(coordinates: list[tuple[float, float]]) -> float:
    distance = 0.0
    for (lng1, lat1), (lng2, lat2) in zip(coordinates, coordinates[1:], strict=False):
        delta_lat = radians(lat2 - lat1)
        delta_lng = radians(lng2 - lng1)
        value = sin(delta_lat / 2) ** 2 + (
            cos(radians(lat1)) * cos(radians(lat2)) * sin(delta_lng / 2) ** 2
        )
        distance += 2 * 6_371_008.8 * asin(sqrt(value))
    return distance
