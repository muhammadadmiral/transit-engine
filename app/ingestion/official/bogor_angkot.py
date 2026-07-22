"""Kabupaten Bogor official angkot polyline adapter."""

import re
from datetime import date
from typing import Any

from app.models.schema import (
    DataConfidence,
    FlexibleRoute,
    ServiceCategory,
    TransportMode,
)

SOURCE_URL = (
    "https://geoportal.bogorkab.go.id/server/rest/services/"
    "Kabisa_Latest/tematik_sektoral_03092026/MapServer/22"
)
VERIFIED_AT = date(2026, 7, 22)


def parse_bogor_features(payloads: list[dict[str, Any]]) -> list[FlexibleRoute]:
    routes: list[FlexibleRoute] = []
    seen: set[tuple[int, int]] = set()
    for payload in payloads:
        for feature in payload.get("features", []):
            attributes = feature.get("attributes") or {}
            category = str(attributes.get("Keterangan") or "")
            if "angkot" not in category.casefold() and "tayek angkot" not in category.casefold():
                continue
            feature_id = int(attributes["FID"])
            name = str(attributes.get("Nama") or f"Trayek Bogor {feature_id}").strip()
            code = _route_code(name, feature_id)
            for path_index, raw_path in enumerate((feature.get("geometry") or {}).get("paths", [])):
                if (feature_id, path_index) in seen or len(raw_path) < 2:
                    continue
                seen.add((feature_id, path_index))
                coordinates = [(float(point[0]), float(point[1])) for point in raw_path]
                route_base = f"angkot:bogor-gis:{feature_id}:{path_index}"
                for direction, ordered in (
                    ("outbound", coordinates),
                    ("inbound", list(reversed(coordinates))),
                ):
                    routes.append(
                        FlexibleRoute(
                            id=f"{route_base}:{direction}",
                            route_code=code,
                            route_name=name,
                            mode=TransportMode.ANGKOT,
                            service_category=ServiceCategory.FEEDER,
                            service_name="Angkot Kabupaten Bogor",
                            avg_speed_kmh=18,
                            fare=5000,
                            fare_product_id="angkot:regular",
                            data_confidence=DataConfidence.OFFICIAL,
                            last_verified_at=VERIFIED_AT,
                            color="22A447",
                            coordinates=ordered,
                            source_url=SOURCE_URL,
                        )
                    )
    return routes


def _route_code(name: str, feature_id: int) -> str:
    match = re.search(r"\b(?:trayek\s+)?(\d{1,3}[a-z]?)\b", name, re.IGNORECASE)
    if match:
        return match.group(1).upper()
    corridor = re.search(r"\bkor(?:idor)?\s*(\d{1,3})\b", name, re.IGNORECASE)
    return f"KOR-{corridor.group(1)}" if corridor else f"BG-{feature_id}"
