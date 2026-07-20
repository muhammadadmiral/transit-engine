from datetime import date

from app.fares.engine import (
    EstimatedRangeFareRule,
    FareCatalog,
    FlatFareRule,
    OdMatrixFareRule,
    quote_journey,
)
from app.models.schema import (
    DataConfidence,
    FareStatus,
    Segment,
    ServiceCategory,
    TransportMode,
)


def segment(
    segment_id: str,
    route_id: str,
    from_stop_id: str,
    to_stop_id: str,
    *,
    product_id: str,
    fare: int,
) -> Segment:
    return Segment(
        id=segment_id,
        route_id=route_id,
        from_stop_id=from_stop_id,
        to_stop_id=to_stop_id,
        mode=TransportMode.TRANSJAKARTA,
        service_category=ServiceCategory.MAIN,
        service_name="Test service",
        avg_duration_min=3,
        fare=fare,
        fare_product_id=product_id,
        data_confidence=DataConfidence.OFFICIAL,
        last_verified_at=date(2026, 7, 20),
        color="009999",
        coordinates=[(106.8, -6.2), (106.81, -6.21)],
    )


def test_flat_product_is_charged_once_across_route_changes() -> None:
    catalog = FareCatalog([FlatFareRule("tj", 3500, "https://example.com/tj")])
    quote = quote_journey(
        [
            segment("one", "route-1", "a", "b", product_id="tj", fare=3500),
            segment("two", "route-2", "b", "c", product_id="tj", fare=3500),
        ],
        catalog=catalog,
    )

    assert quote.status is FareStatus.EXACT
    assert quote.estimated_amount == 3500
    assert len(quote.components) == 1


def test_od_matrix_prices_the_complete_ride() -> None:
    catalog = FareCatalog([OdMatrixFareRule("mrt", {("a", "c"): 5000}, "https://example.com/mrt")])
    quote = quote_journey(
        [
            segment("one", "mrt", "a", "b", product_id="mrt", fare=3000),
            segment("two", "mrt", "b", "c", product_id="mrt", fare=3000),
        ],
        catalog=catalog,
    )

    assert quote.status is FareStatus.EXACT
    assert quote.estimated_amount == 5000


def test_estimated_range_stays_visible_to_api_consumers() -> None:
    catalog = FareCatalog(
        [EstimatedRangeFareRule("angkot", 6000, 5000, 8000, "https://example.com/angkot")]
    )
    quote = quote_journey(
        [segment("one", "angkot-1", "a", "b", product_id="angkot", fare=6000)],
        catalog=catalog,
    )

    assert quote.status is FareStatus.RANGE
    assert (quote.min_amount, quote.estimated_amount, quote.max_amount) == (5000, 6000, 8000)
