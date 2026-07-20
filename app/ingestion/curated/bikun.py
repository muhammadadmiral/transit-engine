"""Curated dataset for Universitas Indonesia Campus Bus (Bikun)."""

from datetime import date
from typing import NamedTuple

from app.ingestion.gtfs.transjakarta import TransitDataset
from app.models.schema import DataConfidence, Segment, ServiceCategory, Stop, TransportMode

VERIFIED_AT = date(2026, 7, 20)


class BikunStop(NamedTuple):
    id: str
    name: str
    lat: float
    lng: float


_STOPS = [
    BikunStop("stasiun-ui", "Halte Stasiun UI", -6.360531, 106.831775),
    BikunStop("menwa", "Halte Menwa", -6.359275, 106.830605),
    BikunStop("fisip", "Halte FISIP", -6.362145, 106.829023),
    BikunStop("psikologi", "Halte Psikologi", -6.364375, 106.829395),
    BikunStop("fkm", "Halte FKM", -6.365311, 106.825225),
    BikunStop("rs-ui", "Halte RS UI", -6.368512, 106.827115),
    BikunStop("vokasi", "Halte Vokasi", -6.367098, 106.822769),
    BikunStop("teknik", "Halte Teknik", -6.362541, 106.821102),
    BikunStop("mipa", "Halte MIPA", -6.361405, 106.824241),
    BikunStop("balairung", "Halte Balairung", -6.362705, 106.825905),
]

_RED_LINE = [
    "stasiun-ui",
    "menwa",
    "fkm",
    "rs-ui",
    "vokasi",
    "teknik",
    "mipa",
    "balairung",
    "fisip",
    "psikologi",
    "stasiun-ui",
]

_BLUE_LINE = [
    "stasiun-ui",
    "psikologi",
    "fisip",
    "balairung",
    "mipa",
    "teknik",
    "vokasi",
    "rs-ui",
    "fkm",
    "menwa",
    "stasiun-ui",
]


def build_bikun_dataset() -> TransitDataset:
    stops: dict[str, Stop] = {}
    for row in _STOPS:
        stop_id = f"bikun:{row.id}"
        stops[row.id] = Stop(
            id=stop_id,
            name=row.name,
            lat=row.lat,
            lng=row.lng,
            modes=[TransportMode.BIKUN],
        )

    segments = _build_line("red", "Bikun Rute Merah", "ED1C24", _RED_LINE, stops)
    segments.extend(_build_line("blue", "Bikun Rute Biru", "00A2E8", _BLUE_LINE, stops))

    return TransitDataset(stops=list(stops.values()), segments=segments)


def _build_line(
    line_id: str,
    line_name: str,
    color: str,
    stop_ids: list[str],
    stops: dict[str, Stop],
) -> list[Segment]:
    return [
        Segment(
            id=f"bikun:{line_id}:{from_id}:{to_id}",
            route_id=f"bikun:{line_id}",
            from_stop_id=f"bikun:{from_id}",
            to_stop_id=f"bikun:{to_id}",
            mode=TransportMode.BIKUN,
            service_category=ServiceCategory.BIKUN,
            service_name=line_name,
            avg_duration_min=3.0,
            fare=0,
            fare_product_id="bikun:regular",
            data_confidence=DataConfidence.COMMUNITY,
            last_verified_at=VERIFIED_AT,
            color=color,
            coordinates=[
                (stops[from_id].lng, stops[from_id].lat),
                (stops[to_id].lng, stops[to_id].lat),
            ],
        )
        for from_id, to_id in zip(stop_ids, stop_ids[1:], strict=True)
    ]
