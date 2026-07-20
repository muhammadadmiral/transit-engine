"""Published regular fares that are stable enough to ship with the service."""

from app.fares.engine import (
    FareCatalog,
    FlatFareRule,
    OdMatrixFareRule,
    TimeDistanceCapFareRule,
)
from app.ingestion.curated.rail import MRT_FARE_SOURCE_URL, MRT_FARES

DEFAULT_FARE_CATALOG = FareCatalog(
    [
        FlatFareRule(
            product_id="transjakarta:regular",
            amount=3500,
            source_url="https://transjakarta.co.id/",
        ),
        FlatFareRule(
            product_id="lrt-jakarta:regular",
            amount=5000,
            source_url="https://www.lrtjakarta.co.id/faq.html?action=FAQ.list&page=3",
        ),
        OdMatrixFareRule(
            product_id="mrt-jakarta:regular",
            fares=MRT_FARES,
            source_url=MRT_FARE_SOURCE_URL,
        ),
        TimeDistanceCapFareRule(
            product_id="lrt-jabodebek:regular",
            base_amount=5000,
            base_distance_km=1,
            per_km_amount=700,
            offpeak_cap=10000,
            peak_cap=20000,
            source_url="https://lrtjabodebek.kai.id/informasi-tarif",
        ),
    ]
)
