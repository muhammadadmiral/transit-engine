"""Reviewed Depok hail-and-ride corridors missing from OSM route relations."""

from dataclasses import dataclass
from datetime import date

from app.ingestion.curated.angkot_depok_additions import (
    D83_INBOUND,
    D83_OUTBOUND,
    D105_INBOUND,
    D105_OUTBOUND,
    M20_INBOUND,
    M20_OUTBOUND,
)
from app.models.schema import DataConfidence, FlexibleRoute, ServiceCategory, TransportMode

VERIFIED_AT = date(2026, 7, 22)
SOURCE_URL = "https://jdih.depok.go.id/uploads/FileFinalProduk/20250422100127_2025pw3224007.pdf"
BPTJ_SOURCE_URL = (
    "https://ppid.kemenhub.go.id/fileupload/informasi-berkala/"
    "20250508143913.LKIP_BPTJ_2024_compressed-dikompresi_%281%29.pdf"
)


@dataclass(frozen=True)
class CuratedRoute:
    code: str
    name: str
    outbound_geometry: tuple[tuple[float, float], ...]
    inbound_geometry: tuple[tuple[float, float], ...] | None = None
    source_url: str = SOURCE_URL


# Terminal Depok -> Parung via AR Hakim, Nusantara, Sawangan, Muchtar, Parung.
_D03 = (
    (106.824723, -6.391633),
    (106.825422, -6.390363),
    (106.825317, -6.390124),
    (106.821806, -6.390156),
    (106.820883, -6.389887),
    (106.819056, -6.389017),
    (106.818252, -6.388844),
    (106.815603, -6.388984),
    (106.814266, -6.388884),
    (106.814717, -6.393183),
    (106.813488, -6.399045),
    (106.813116, -6.399147),
    (106.809658, -6.398136),
    (106.808303, -6.397592),
    (106.806040, -6.397161),
    (106.803069, -6.395651),
    (106.802839, -6.395404),
    (106.802594, -6.394764),
    (106.802392, -6.394667),
    (106.801270, -6.394608),
    (106.799620, -6.394998),
    (106.797617, -6.394948),
    (106.792046, -6.394281),
    (106.789047, -6.394199),
    (106.788373, -6.393886),
    (106.787638, -6.394018),
    (106.784195, -6.395194),
    (106.781567, -6.395753),
    (106.775560, -6.396093),
    (106.772836, -6.394699),
    (106.772563, -6.395508),
    (106.771785, -6.396708),
    (106.771607, -6.401111),
    (106.770781, -6.403021),
    (106.770259, -6.403417),
    (106.769690, -6.403507),
    (106.767673, -6.403320),
    (106.766994, -6.403547),
    (106.766177, -6.403541),
    (106.764993, -6.404430),
    (106.763930, -6.405020),
    (106.762080, -6.405398),
    (106.760621, -6.405899),
    (106.760086, -6.405889),
    (106.758966, -6.405485),
    (106.758475, -6.405465),
    (106.757317, -6.405845),
    (106.756056, -6.407421),
    (106.755129, -6.407638),
    (106.753517, -6.407404),
    (106.748353, -6.405799),
    (106.743915, -6.405218),
    (106.741743, -6.404612),
    (106.741402, -6.405786),
    (106.740778, -6.406310),
    (106.740306, -6.406416),
    (106.738003, -6.406218),
    (106.737446, -6.406459),
    (106.737133, -6.406819),
    (106.734664, -6.413085),
    (106.732769, -6.421787),
    (106.732646, -6.421449),
)

# Terminal Depok -> Palsigunung via Margonda and Akses UI.  The Jalan Sawo
# loop is retained because it is the practical boarding point from Stasiun UI.
_D11 = (
    (106.824723, -6.391633),
    (106.826141, -6.388908),
    (106.828246, -6.386266),
    (106.828709, -6.385367),
    (106.831639, -6.377706),
    (106.832435, -6.373917),
    (106.833965, -6.368598),
    (106.833917, -6.366246),
    (106.833681, -6.366270),
    (106.832886, -6.364101),
    (106.832400, -6.363986),
    (106.833046, -6.361164),
    (106.832400, -6.363986),
    (106.832886, -6.364101),
    (106.833681, -6.366270),
    (106.833917, -6.366246),
    (106.833377, -6.361254),
    (106.831973, -6.356383),
    (106.831930, -6.355347),
    (106.832040, -6.355054),
    (106.833112, -6.355228),
    (106.834786, -6.355158),
    (106.836759, -6.354048),
    (106.837422, -6.353840),
    (106.838336, -6.354039),
    (106.840396, -6.354827),
    (106.844071, -6.354954),
    (106.846605, -6.354786),
    (106.849735, -6.355395),
    (106.851870, -6.355343),
    (106.855548, -6.355918),
    (106.856244, -6.356152),
    (106.858907, -6.357574),
    (106.858883, -6.358002),
)

ROUTES = (
    CuratedRoute("D03", "Terminal Depok – Parung via Sawangan", _D03),
    CuratedRoute("D11", "Terminal Depok – Palsigunung via Akses UI", _D11),
    CuratedRoute(
        "D83",
        "Tanah Baru – Lenteng Agung via Srengseng Sawah",
        D83_OUTBOUND,
        D83_INBOUND,
        BPTJ_SOURCE_URL,
    ),
    CuratedRoute(
        "D105",
        "Terminal Depok – Pondok Labu via Tanah Baru dan Gandul",
        D105_OUTBOUND,
        D105_INBOUND,
        BPTJ_SOURCE_URL,
    ),
    CuratedRoute(
        "M20",
        "Terminal Pasar Minggu – Ciganjur via Cilandak KKO",
        M20_OUTBOUND,
        M20_INBOUND,
        BPTJ_SOURCE_URL,
    ),
)


def build_depok_angkot_routes() -> list[FlexibleRoute]:
    result: list[FlexibleRoute] = []
    for route in ROUTES:
        route_key = route.code.casefold()
        for direction, coordinates in (
            ("outbound", route.outbound_geometry),
            ("inbound", route.inbound_geometry or tuple(reversed(route.outbound_geometry))),
        ):
            result.append(
                FlexibleRoute(
                    id=f"angkot:depok:{route_key}:{direction}",
                    route_code=route.code,
                    route_name=route.name,
                    mode=TransportMode.ANGKOT,
                    service_category=ServiceCategory.FEEDER,
                    service_name=f"Angkot Depok {route.code}",
                    avg_speed_kmh=16.8,
                    fare=5000,
                    fare_product_id="angkot:depok:regular",
                    data_confidence=DataConfidence.COMMUNITY,
                    last_verified_at=VERIFIED_AT,
                    color="F59E0B",
                    coordinates=list(coordinates),
                    source_url=route.source_url,
                )
            )
    return result
