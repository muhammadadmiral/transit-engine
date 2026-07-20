"""Versioned KRL Jabodetabek topology and station coordinates.

Line topology is checked against KAI Commuter's published operating pattern and
timetable. Coordinates are a 2026-07-20 OpenStreetMap snapshot (ODbL). Keeping
the compact snapshot here makes imports deterministic and prevents the runtime
API from depending on a public Overpass/OpenStreetMap service.
"""

from datetime import date
from itertools import pairwise
from math import asin, cos, radians, sin, sqrt

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
KRL_NETWORK_SOURCE_URL = (
    "https://www.commuterline.id/informasi-publik/berita/"
    "kai-commuter-terus-lakukan-sosialisasi-perubahan-pola-operasi-terkait-gapeka-baru-khusus-krl-dan"
)
KRL_TIMETABLE_SOURCE_URL = (
    "https://commuterline.id/files/download/documents/"
    "Jadwal%20Commuter%20Line%20Jabodetabek%20-%20Mulai%201%20Februari%202025.pdf"
)
KRL_COORDINATE_SOURCE_URL = "https://www.openstreetmap.org/copyright"
KRL_FARE_SOURCE_URL = (
    "https://www.commuterline.id/informasi-publik/berita/"
    "tarif-commuterline-jabodetabek-masih-sesuai-dengan-keputusan-menteri-perhubungan-"
    "no-354-tahun-2020-kai-commuter-koordinasi-dengan-pemerintah-terkait-penyesuaian-tarif"
)

# slug: (display name, latitude, longitude)
KRL_STATIONS = {
    "jakarta-kota": ("Jakarta Kota", -6.1374675, 106.8161187),
    "jayakarta": ("Jayakarta", -6.1420959, 106.8235244),
    "mangga-besar": ("Mangga Besar", -6.1512727, 106.8272222),
    "sawah-besar": ("Sawah Besar", -6.1617916, 106.8280399),
    "juanda": ("Juanda", -6.1675618, 106.8304676),
    "gondangdia": ("Gondangdia", -6.1869328, 106.8328895),
    "cikini": ("Cikini", -6.1993745, 106.8418573),
    "manggarai": ("Manggarai", -6.2112049, 106.8503080),
    "tebet": ("Tebet", -6.2275317, 106.8584280),
    "cawang": ("Cawang", -6.2425503, 106.8586732),
    "duren-kalibata": ("Duren Kalibata", -6.2554463, 106.8550306),
    "pasar-minggu-baru": ("Pasar Minggu Baru", -6.2642983, 106.8510992),
    "pasar-minggu": ("Pasar Minggu", -6.2837674, 106.8447574),
    "tanjung-barat": ("Tanjung Barat", -6.3096921, 106.8386475),
    "lenteng-agung": ("Lenteng Agung", -6.3306245, 106.8348170),
    "universitas-pancasila": ("Universitas Pancasila", -6.3406626, 106.8339225),
    "universitas-indonesia": ("Universitas Indonesia", -6.3605313, 106.8317755),
    "pondok-cina": ("Pondok Cina", -6.3689544, 106.8320943),
    "depok-baru": ("Depok Baru", -6.3920709, 106.8212108),
    "depok": ("Depok", -6.4050226, 106.8169425),
    "citayam": ("Citayam", -6.4500288, 106.8020558),
    "bojonggede": ("Bojonggede", -6.4940161, 106.7949591),
    "cilebut": ("Cilebut", -6.5321020, 106.8005129),
    "bogor": ("Bogor", -6.5942843, 106.7907239),
    "cibinong": ("Cibinong", -6.4639777, 106.8533411),
    "nambo": ("Nambo", -6.4668163, 106.9055193),
    "rangkasbitung": ("Rangkasbitung", -6.3530751, 106.2531322),
    "citeras": ("Citeras", -6.3348861, 106.3339336),
    "maja": ("Maja", -6.3326947, 106.3969176),
    "tigaraksa": ("Tigaraksa", -6.3284495, 106.4350892),
    "tenjo": ("Tenjo", -6.3275269, 106.4620439),
    "daru": ("Daru", -6.3387960, 106.4929563),
    "cilejit": ("Cilejit", -6.3548449, 106.5105045),
    "parung-panjang": ("Parung Panjang", -6.3443931, 106.5702988),
    "jatake": ("Jatake", -6.3347636, 106.6077383),
    "cicayur": ("Cicayur", -6.3292330, 106.6201894),
    "cisauk": ("Cisauk", -6.3240322, 106.6424646),
    "serpong": ("Serpong", -6.3201800, 106.6666299),
    "rawa-buntu": ("Rawa Buntu", -6.3145503, 106.6767836),
    "sudimara": ("Sudimara", -6.2962511, 106.7137361),
    "jurangmangu": ("Jurangmangu", -6.2885283, 106.7292619),
    "pondok-ranji": ("Pondok Ranji", -6.2763321, 106.7452082),
    "kebayoran": ("Kebayoran", -6.2359947, 106.7829591),
    "palmerah": ("Palmerah", -6.2062224, 106.7980546),
    "tanah-abang": ("Tanah Abang", -6.1839042, 106.8106768),
    "duri": ("Duri", -6.1565236, 106.8012402),
    "grogol": ("Grogol", -6.1619976, 106.7872681),
    "pesing": ("Pesing", -6.1611889, 106.7715864),
    "taman-kota": ("Taman Kota", -6.1581842, 106.7545627),
    "bojong-indah": ("Bojong Indah", -6.1605372, 106.7350302),
    "rawa-buaya": ("Rawa Buaya", -6.1627563, 106.7227805),
    "kalideres": ("Kalideres", -6.1661506, 106.7025108),
    "poris": ("Poris", -6.1697901, 106.6802736),
    "batu-ceper": ("Batu Ceper", -6.1724069, 106.6639437),
    "tanah-tinggi": ("Tanah Tinggi", -6.1752995, 106.6457290),
    "tangerang": ("Tangerang", -6.1768139, 106.6307174),
    "kampung-bandan": ("Kampung Bandan", -6.1328911, 106.8287448),
    "ancol": ("Ancol", -6.1278550, 106.8464560),
    "tanjung-priok": ("Tanjung Priok", -6.1106006, 106.8814496),
    "cikarang": ("Cikarang", -6.2555519, 107.1457636),
    "metland-telagamurni": ("Metland Telagamurni", -6.2576096, 107.1102351),
    "cibitung": ("Cibitung", -6.2618585, 107.0832401),
    "tambun": ("Tambun", -6.2581362, 107.0543693),
    "bekasi-timur": ("Bekasi Timur", -6.2463179, 107.0169738),
    "bekasi": ("Bekasi", -6.2352405, 106.9971258),
    "kranji": ("Kranji", -6.2238316, 106.9788886),
    "cakung": ("Cakung", -6.2190888, 106.9520607),
    "klender-baru": ("Klender Baru", -6.2174890, 106.9392621),
    "buaran": ("Buaran", -6.2153263, 106.9214031),
    "klender": ("Klender", -6.2132396, 106.8986471),
    "jatinegara": ("Jatinegara", -6.2150118, 106.8692829),
    "matraman": ("Matraman", -6.2128788, 106.8589171),
    "sudirman": ("Sudirman", -6.2026049, 106.8243422),
    "bni-city": ("BNI City", -6.2013528, 106.8186815),
    "karet": ("Karet", -6.2007639, 106.8159745),
    "angke": ("Angke", -6.1435409, 106.8006901),
    "pondok-jati": ("Pondok Jati", -6.2085627, 106.8622121),
    "kramat": ("Kramat", -6.1922610, 106.8554903),
    "gang-sentiong": ("Gang Sentiong", -6.1852414, 106.8501981),
    "pasar-senen": ("Pasar Senen", -6.1727569, 106.8440952),
    "kemayoran": ("Kemayoran", -6.1607633, 106.8412461),
    "rajawali": ("Rajawali", -6.1444256, 106.8366149),
}

BOGOR_MAIN = (
    "jakarta-kota",
    "jayakarta",
    "mangga-besar",
    "sawah-besar",
    "juanda",
    "gondangdia",
    "cikini",
    "manggarai",
    "tebet",
    "cawang",
    "duren-kalibata",
    "pasar-minggu-baru",
    "pasar-minggu",
    "tanjung-barat",
    "lenteng-agung",
    "universitas-pancasila",
    "universitas-indonesia",
    "pondok-cina",
    "depok-baru",
    "depok",
    "citayam",
    "bojonggede",
    "cilebut",
    "bogor",
)
NAMBO_BRANCH = ("citayam", "cibinong", "nambo")
RANGKASBITUNG_LINE = (
    "tanah-abang",
    "palmerah",
    "kebayoran",
    "pondok-ranji",
    "jurangmangu",
    "sudimara",
    "rawa-buntu",
    "serpong",
    "cisauk",
    "cicayur",
    "jatake",
    "parung-panjang",
    "cilejit",
    "daru",
    "tenjo",
    "tigaraksa",
    "maja",
    "citeras",
    "rangkasbitung",
)
TANGERANG_LINE = (
    "duri",
    "grogol",
    "pesing",
    "taman-kota",
    "bojong-indah",
    "rawa-buaya",
    "kalideres",
    "poris",
    "batu-ceper",
    "tanah-tinggi",
    "tangerang",
)
TANJUNG_PRIOK_LINE = ("jakarta-kota", "kampung-bandan", "ancol", "tanjung-priok")
CIKARANG_TRUNK = (
    "cikarang",
    "metland-telagamurni",
    "cibitung",
    "tambun",
    "bekasi-timur",
    "bekasi",
    "kranji",
    "cakung",
    "klender-baru",
    "buaran",
    "klender",
    "jatinegara",
)
CIKARANG_SOUTH_ARC = (
    "jatinegara",
    "matraman",
    "manggarai",
    "sudirman",
    "bni-city",
    "karet",
    "tanah-abang",
    "duri",
    "angke",
    "kampung-bandan",
)
CIKARANG_NORTH_ARC = (
    "jatinegara",
    "pondok-jati",
    "kramat",
    "gang-sentiong",
    "pasar-senen",
    "kemayoran",
    "rajawali",
    "kampung-bandan",
)

KRL_ROUTES = (
    ("krl:bogor-line", "Commuter Line Bogor", "EC1C24", BOGOR_MAIN),
    ("krl:bogor-line", "Commuter Line Bogor", "EC1C24", NAMBO_BRANCH),
    ("krl:rangkasbitung-line", "Commuter Line Rangkasbitung", "98CA3F", RANGKASBITUNG_LINE),
    ("krl:tangerang-line", "Commuter Line Tangerang", "A35EA8", TANGERANG_LINE),
    ("krl:tanjung-priok-line", "Commuter Line Tanjung Priok", "EF7622", TANJUNG_PRIOK_LINE),
    ("krl:cikarang-loop-line", "Commuter Line Cikarang", "26BAED", CIKARANG_TRUNK),
    ("krl:cikarang-loop-line", "Commuter Line Cikarang", "26BAED", CIKARANG_SOUTH_ARC),
    ("krl:cikarang-loop-line", "Commuter Line Cikarang", "26BAED", CIKARANG_NORTH_ARC),
)


def build_krl_dataset() -> TransitDataset:
    stops = [
        Stop(id=f"krl:{slug}", name=name, lat=lat, lng=lng, modes=[TransportMode.KRL])
        for slug, (name, lat, lng) in KRL_STATIONS.items()
    ]
    segments = [
        segment
        for route_id, service_name, color, station_ids in KRL_ROUTES
        for segment in _line_segments(route_id, service_name, color, station_ids)
    ]
    return TransitDataset(stops=stops, segments=segments)


def _line_segments(
    route_id: str,
    service_name: str,
    color: str,
    station_ids: tuple[str, ...],
) -> list[Segment]:
    segments = []
    for first_id, second_id in pairwise(station_ids):
        segments.extend(
            [
                _segment(route_id, service_name, color, first_id, second_id),
                _segment(route_id, service_name, color, second_id, first_id),
            ]
        )
    return segments


def _segment(
    route_id: str,
    service_name: str,
    color: str,
    from_id: str,
    to_id: str,
) -> Segment:
    _, from_lat, from_lng = KRL_STATIONS[from_id]
    _, to_lat, to_lng = KRL_STATIONS[to_id]
    distance_km = _distance_km(from_lat, from_lng, to_lat, to_lng)
    duration_min = round(max(2.2, distance_km / 48 * 60 + 0.8), 1)
    from_stop_id = f"krl:{from_id}"
    to_stop_id = f"krl:{to_id}"
    fallback = [(from_lng, from_lat), (to_lng, to_lat)]
    return Segment(
        id=f"{route_id}:{from_id}:{to_id}",
        route_id=route_id,
        from_stop_id=from_stop_id,
        to_stop_id=to_stop_id,
        mode=TransportMode.KRL,
        service_category=ServiceCategory.MAIN,
        service_name=service_name,
        avg_duration_min=duration_min,
        fare=3000,
        fare_product_id="krl-jabodetabek:regular",
        data_confidence=DataConfidence.COMMUNITY,
        last_verified_at=VERIFIED_AT,
        color=color,
        coordinates=segment_geometry(route_id, from_stop_id, to_stop_id, fallback),
    )


def _distance_km(from_lat: float, from_lng: float, to_lat: float, to_lng: float) -> float:
    delta_lat = radians(to_lat - from_lat)
    delta_lng = radians(to_lng - from_lng)
    value = sin(delta_lat / 2) ** 2 + (
        cos(radians(from_lat)) * cos(radians(to_lat)) * sin(delta_lng / 2) ** 2
    )
    return 2 * 6371.0088 * asin(sqrt(value))
