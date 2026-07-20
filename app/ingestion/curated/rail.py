"""Official-source MRT Jakarta and LRT Jakarta operating network.

No public operator GTFS feed was discoverable when verified on 2026-07-20, so
this small network is deliberately source-controlled and validated. Planned
stations are excluded until commercial operations begin.
"""

from datetime import date
from itertools import pairwise

from app.ingestion.curated.geometry import segment_geometry
from app.ingestion.gtfs.transjakarta import TransitDataset
from app.models.schema import (
    DataConfidence,
    Segment,
    ServiceCategory,
    Stop,
    TransportMode,
)

VERIFIED_AT = date(2026, 7, 20)
MRT_STATION_SOURCE_URL = "https://www.jakartamrt.co.id/daftar-stasiun"
LRT_STATION_SOURCE_URL = "https://www.lrtjakarta.co.id/faq22.html"
COORDINATE_SOURCE_URL = (
    "https://gis-dpmptsp.jakarta.go.id/arcgis/rest/services/Hosted/"
    "Titik_Transportasi_Umum_Jakarta_v3/FeatureServer/26"
)
MRT_FARE_SOURCE_URL = "https://jdih.jakarta.go.id/dokumenPeraturanDirectory/0031/201925034.pdf"
LRT_FARE_SOURCE_URL = "https://www.lrtjakarta.co.id/faq.html?action=FAQ.list&page=3"
LRT_JABODEBEK_STATION_SOURCE_URL = "https://lrtjabodebek.kai.id/stations"
LRT_JABODEBEK_COORDINATE_SOURCE_URL = "https://www.openstreetmap.org/copyright"

MRT_STATIONS = (
    ("lebak-bulus", "Lebak Bulus BSI", -6.28950821, 106.77484959),
    ("fatmawati", "Fatmawati Indomaret", -6.29263282, 106.79279160),
    ("cipete-raya", "Cipete Raya", -6.27851180, 106.79740539),
    ("haji-nawi", "Haji Nawi", -6.26631586, 106.79735882),
    ("blok-a", "Blok A", -6.25567523, 106.79722680),
    ("blok-m", "Blok M BCA", -6.24490165, 106.79819411),
    ("asean", "ASEAN", -6.23858506, 106.79844032),
    ("senayan", "Senayan Mastercard", -6.22675017, 106.80285595),
    ("istora", "Istora Mandiri", -6.22283480, 106.80844309),
    ("bendungan-hilir", "Bendungan Hilir", -6.21508310, 106.81744440),
    ("setiabudi", "Setiabudi Astra", -6.20926559, 106.82134082),
    ("dukuh-atas", "Dukuh Atas BNI", -6.19937825, 106.82331852),
    ("bundaran-hi", "Bundaran HI Bank DKI", -6.19266391, 106.82306838),
)

LRT_JAKARTA_STATIONS = (
    ("pegangsaan-dua", "Pegangsaan Dua", -6.15504823, 106.91559581),
    ("boulevard-utara", "Boulevard Utara", -6.15937570, 106.90602670),
    ("boulevard-selatan", "Boulevard Selatan", -6.16933790, 106.89974981),
    ("pulomas", "Pulomas", -6.17716409, 106.89345618),
    ("equestrian", "Equestrian", -6.18351300, 106.89130374),
    ("velodrome", "Velodrome", -6.19229767, 106.89122420),
)

LRT_JABODEBEK_COMMON_STATIONS = (
    ("dukuh-atas", "Dukuh Atas BNI", -6.2048280, 106.8255301),
    ("setiabudi", "Setiabudi", -6.2093184, 106.8302209),
    ("rasuna-said", "Rasuna Said", -6.2216089, 106.8322373),
    ("kuningan", "Kuningan", -6.2287727, 106.8332031),
    ("pancoran", "Pancoran bank bjb", -6.2421415, 106.8385146),
    ("cikoko", "Cikoko", -6.2434846, 106.8570718),
    ("ciliwung", "Ciliwung", -6.2434461, 106.8639705),
    ("cawang", "Cawang", -6.2459070, 106.8712296),
)

LRT_JABODEBEK_BEKASI_STATIONS = (
    ("halim", "Halim", -6.2458656, 106.8872875),
    ("jatibening-baru", "Jatibening Baru", -6.2577476, 106.9279199),
    ("cikunir-1", "Cikunir 1", -6.2566001, 106.9518734),
    ("cikunir-2", "Cikunir 2", -6.2546502, 106.9632112),
    ("bekasi-barat", "Bekasi Barat", -6.2529489, 106.9904237),
    ("jatimulya", "Jatimulya", -6.2641077, 107.0216701),
)

LRT_JABODEBEK_CIBUBUR_STATIONS = (
    ("taman-mini", "Taman Mini", -6.2929088, 106.8805584),
    ("kampung-rambutan", "Kampung Rambutan", -6.3095494, 106.8843804),
    ("ciracas", "Ciracas", -6.3237693, 106.8866433),
    ("harjamukti", "Harjamukti", -6.3738926, 106.8956698),
)

LRT_JABODEBEK_STATIONS = (
    *LRT_JABODEBEK_COMMON_STATIONS,
    *LRT_JABODEBEK_BEKASI_STATIONS,
    *LRT_JABODEBEK_CIBUBUR_STATIONS,
)

_MRT_FARE_ROWS = (
    (3000, 4000, 5000, 6000, 7000, 8000, 9000, 10000, 11000, 12000, 13000, 14000, 14000),
    (4000, 3000, 4000, 5000, 6000, 7000, 7000, 9000, 9000, 10000, 11000, 12000, 13000),
    (5000, 4000, 3000, 3000, 4000, 5000, 6000, 7000, 8000, 9000, 9000, 10000, 11000),
    (6000, 5000, 3000, 3000, 3000, 4000, 5000, 6000, 7000, 8000, 8000, 9000, 10000),
    (7000, 6000, 4000, 3000, 3000, 3000, 4000, 5000, 6000, 7000, 7000, 8000, 9000),
    (8000, 7000, 5000, 4000, 3000, 3000, 3000, 4000, 5000, 6000, 6000, 7000, 8000),
    (9000, 7000, 6000, 5000, 4000, 3000, 3000, 3000, 4000, 5000, 6000, 7000, 7000),
    (10000, 9000, 7000, 6000, 5000, 4000, 3000, 3000, 3000, 4000, 4000, 5000, 6000),
    (11000, 9000, 8000, 7000, 6000, 5000, 4000, 3000, 3000, 3000, 3000, 4000, 5000),
    (12000, 10000, 9000, 8000, 7000, 6000, 5000, 4000, 3000, 3000, 3000, 3000, 4000),
    (13000, 11000, 9000, 8000, 7000, 6000, 6000, 4000, 3000, 3000, 3000, 3000, 4000),
    (14000, 12000, 10000, 9000, 8000, 7000, 7000, 5000, 4000, 3000, 3000, 3000, 3000),
    (14000, 13000, 11000, 10000, 9000, 8000, 7000, 6000, 5000, 4000, 4000, 3000, 3000),
)

MRT_FARES = {
    (f"mrt:{origin[0]}", f"mrt:{destination[0]}"): fare
    for origin, row in zip(MRT_STATIONS, _MRT_FARE_ROWS, strict=True)
    for destination, fare in zip(MRT_STATIONS, row, strict=True)
}


def build_rail_dataset() -> TransitDataset:
    stops = [
        *_stops("mrt", MRT_STATIONS, TransportMode.MRT),
        *_stops("lrt-jakarta", LRT_JAKARTA_STATIONS, TransportMode.LRT),
        *_stops("lrt-jabodebek", LRT_JABODEBEK_STATIONS, TransportMode.LRT),
    ]
    segments = [
        *_line_segments(
            namespace="mrt",
            stations=MRT_STATIONS,
            route_id="mrt:north-south",
            mode=TransportMode.MRT,
            service_name="MRT Jakarta",
            color="106EE8",
            duration_min=2.5,
            fare=3000,
            fare_product_id="mrt-jakarta:regular",
        ),
        *_line_segments(
            namespace="lrt-jakarta",
            stations=LRT_JAKARTA_STATIONS,
            route_id="lrt-jakarta:line-1",
            mode=TransportMode.LRT,
            service_name="LRT Jakarta",
            color="21409A",
            duration_min=2.8,
            fare=5000,
            fare_product_id="lrt-jakarta:regular",
        ),
        *_line_segments(
            namespace="lrt-jabodebek",
            stations=(
                *LRT_JABODEBEK_COMMON_STATIONS,
                *LRT_JABODEBEK_BEKASI_STATIONS,
            ),
            route_id="lrt-jabodebek:bekasi",
            mode=TransportMode.LRT,
            service_name="LRT Jabodebek - Bekasi Line",
            color="ED1B2F",
            duration_min=5,
            fare=5000,
            fare_product_id="lrt-jabodebek:regular",
            data_confidence=DataConfidence.COMMUNITY,
        ),
        *_line_segments(
            namespace="lrt-jabodebek",
            stations=(
                *LRT_JABODEBEK_COMMON_STATIONS,
                *LRT_JABODEBEK_CIBUBUR_STATIONS,
            ),
            route_id="lrt-jabodebek:cibubur",
            mode=TransportMode.LRT,
            service_name="LRT Jabodebek - Cibubur Line",
            color="204B9B",
            duration_min=5,
            fare=5000,
            fare_product_id="lrt-jabodebek:regular",
            data_confidence=DataConfidence.COMMUNITY,
        ),
    ]
    return TransitDataset(stops=stops, segments=segments)


def _stops(
    namespace: str,
    stations: tuple[tuple[str, str, float, float], ...],
    mode: TransportMode,
) -> list[Stop]:
    return [
        Stop(id=f"{namespace}:{station_id}", name=name, lat=lat, lng=lng, modes=[mode])
        for station_id, name, lat, lng in stations
    ]


def _line_segments(
    *,
    namespace: str,
    stations: tuple[tuple[str, str, float, float], ...],
    route_id: str,
    mode: TransportMode,
    service_name: str,
    color: str,
    duration_min: float,
    fare: int,
    fare_product_id: str,
    data_confidence: DataConfidence = DataConfidence.OFFICIAL,
) -> list[Segment]:
    segments = []
    for first, second in pairwise(stations):
        segments.extend(
            [
                _segment(
                    namespace,
                    route_id,
                    mode,
                    service_name,
                    color,
                    duration_min,
                    fare,
                    fare_product_id,
                    data_confidence,
                    first,
                    second,
                ),
                _segment(
                    namespace,
                    route_id,
                    mode,
                    service_name,
                    color,
                    duration_min,
                    fare,
                    fare_product_id,
                    data_confidence,
                    second,
                    first,
                ),
            ]
        )
    return segments


def _segment(
    namespace: str,
    route_id: str,
    mode: TransportMode,
    service_name: str,
    color: str,
    duration_min: float,
    fare: int,
    fare_product_id: str,
    data_confidence: DataConfidence,
    from_station: tuple[str, str, float, float],
    to_station: tuple[str, str, float, float],
) -> Segment:
    from_id, _, from_lat, from_lng = from_station
    to_id, _, to_lat, to_lng = to_station
    from_stop_id = f"{namespace}:{from_id}"
    to_stop_id = f"{namespace}:{to_id}"
    fallback = [(from_lng, from_lat), (to_lng, to_lat)]
    return Segment(
        id=f"{route_id}:{from_id}:{to_id}",
        route_id=route_id,
        from_stop_id=from_stop_id,
        to_stop_id=to_stop_id,
        mode=mode,
        service_category=ServiceCategory.MAIN,
        service_name=service_name,
        avg_duration_min=duration_min,
        fare=fare,
        fare_product_id=fare_product_id,
        data_confidence=data_confidence,
        last_verified_at=VERIFIED_AT,
        color=color,
        coordinates=segment_geometry(route_id, from_stop_id, to_stop_id, fallback),
    )
