"""Curated dataset for Universitas Indonesia Campus Bus (Bikun)."""

from datetime import date
from typing import NamedTuple

from app.models.schema import DataConfidence, Segment, ServiceCategory, Stop, TransportMode

VERIFIED_AT = date(2026, 7, 20)

class BikunStop(NamedTuple):
    id: str
    name: str
    lat: float
    lng: float

_STOPS = [
    BikunStop("stasiun-ui", "Halte Stasiun UI", -6.360531, 106.831775),
    BikunStop("asrama", "Halte Asrama", -6.353385, 106.831411),
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
    "stasiun-ui", "menwa", "fkm", "rs-ui", "vokasi", "teknik", "mipa", "balairung", "fisip", "psikologi", "stasiun-ui"
]

_BLUE_LINE = [
    "stasiun-ui", "psikologi", "fisip", "balairung", "mipa", "teknik", "vokasi", "rs-ui", "fkm", "menwa", "stasiun-ui"
]

class TransitDataset(NamedTuple):
    stops: list[Stop]
    segments: list[Segment]

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

    segments: list[Segment] = []
    
    # Rute Merah
    for i in range(len(_RED_LINE) - 1):
        from_id = _RED_LINE[i]
        to_id = _RED_LINE[i+1]
        segments.append(
            Segment(
                id=f"bikun:red:{from_id}:{to_id}",
                route_id="bikun:red",
                from_stop_id=f"bikun:{from_id}",
                to_stop_id=f"bikun:{to_id}",
                mode=TransportMode.BIKUN,
                service_category=ServiceCategory.BIKUN,
                service_name="Bikun Rute Merah",
                avg_duration_min=3.0,
                fare=0,
                fare_product_id="bikun:regular",
                data_confidence=DataConfidence.COMMUNITY,
                last_verified_at=VERIFIED_AT,
                color="ED1C24",
                coordinates=[
                    (stops[from_id].lng, stops[from_id].lat),
                    (stops[to_id].lng, stops[to_id].lat),
                ],
            )
        )
        
    # Rute Biru
    for i in range(len(_BLUE_LINE) - 1):
        from_id = _BLUE_LINE[i]
        to_id = _BLUE_LINE[i+1]
        segments.append(
            Segment(
                id=f"bikun:blue:{from_id}:{to_id}",
                route_id="bikun:blue",
                from_stop_id=f"bikun:{from_id}",
                to_stop_id=f"bikun:{to_id}",
                mode=TransportMode.BIKUN,
                service_category=ServiceCategory.BIKUN,
                service_name="Bikun Rute Biru",
                avg_duration_min=3.0,
                fare=0,
                fare_product_id="bikun:regular",
                data_confidence=DataConfidence.COMMUNITY,
                last_verified_at=VERIFIED_AT,
                color="00A2E8",
                coordinates=[
                    (stops[from_id].lng, stops[from_id].lat),
                    (stops[to_id].lng, stops[to_id].lat),
                ],
            )
        )

    return TransitDataset(stops=list(stops.values()), segments=segments)
