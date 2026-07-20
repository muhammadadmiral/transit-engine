"""Pure fare calculation over complete transit journeys.

Fares intentionally live outside graph edges: a flat boarding fare, an
origin/destination matrix, and a distance band cannot be represented faithfully
by one additive number on every segment.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from math import ceil

from app.models.schema import (
    FareComponent,
    FareModel,
    FareQuote,
    FareStatus,
    PaymentProfile,
    Segment,
)


@dataclass(frozen=True)
class FlatFareRule:
    product_id: str
    amount: int
    source_url: str
    model: FareModel = FareModel.FLAT


@dataclass(frozen=True)
class OdMatrixFareRule:
    product_id: str
    fares: Mapping[tuple[str, str], int]
    source_url: str
    model: FareModel = FareModel.OD_MATRIX


@dataclass(frozen=True)
class DistanceBandFareRule:
    product_id: str
    base_amount: int
    base_distance_km: float
    band_amount: int
    band_distance_km: float
    source_url: str
    model: FareModel = FareModel.DISTANCE_BANDS


@dataclass(frozen=True)
class EstimatedRangeFareRule:
    product_id: str
    estimated_amount: int
    min_amount: int
    max_amount: int
    source_url: str | None
    model: FareModel = FareModel.ESTIMATED_RANGE


FareRule = FlatFareRule | OdMatrixFareRule | DistanceBandFareRule | EstimatedRangeFareRule


class FareCatalog:
    def __init__(self, rules: Sequence[FareRule] = ()) -> None:
        self._rules = {rule.product_id: rule for rule in rules}

    def get(self, product_id: str) -> FareRule | None:
        return self._rules.get(product_id)


def quote_journey(
    segments: list[Segment],
    *,
    catalog: FareCatalog,
    departure_at: datetime | None = None,
    payment_profile: PaymentProfile = PaymentProfile.STANDARD,
) -> FareQuote:
    del departure_at  # Reserved for time-dependent LRT Jabodebek rules.
    if not segments:
        return FareQuote(
            status=FareStatus.EXACT,
            estimated_amount=0,
            min_amount=0,
            max_amount=0,
            payment_profile=payment_profile,
            components=[],
        )

    components = [_quote_ride(ride, catalog) for ride in _fare_rides(segments)]
    statuses = {component.status for component in components}
    status = _combined_status(statuses)
    assumptions = []
    if payment_profile is PaymentProfile.JAKLINGKO_INTEGRATED:
        assumptions.append(
            "Integrated-fare eligibility is not applied yet; standard published fares are shown."
        )
    return FareQuote(
        status=status,
        estimated_amount=sum(component.estimated_amount for component in components),
        min_amount=sum(component.min_amount for component in components),
        max_amount=sum(component.max_amount for component in components),
        payment_profile=payment_profile,
        components=components,
        assumptions=assumptions,
    )


def _fare_rides(segments: list[Segment]) -> list[list[Segment]]:
    rides: list[list[Segment]] = []
    current: list[Segment] = []
    current_product: str | None = None
    current_fallback_route: str | None = None
    for segment in segments:
        product = segment.fare_product_id
        same_ride = bool(current) and (
            (product is not None and product == current_product)
            or (
                product is None
                and current_product is None
                and segment.route_id == current_fallback_route
            )
        )
        if not same_ride:
            if current:
                rides.append(current)
            current = []
        current.append(segment)
        current_product = product
        current_fallback_route = segment.route_id
    if current:
        rides.append(current)
    return rides


def _quote_ride(ride: list[Segment], catalog: FareCatalog) -> FareComponent:
    first = ride[0]
    product_id = first.fare_product_id or f"legacy:{first.route_id}"
    rule = catalog.get(product_id)
    if rule is None:
        return FareComponent(
            fare_product_id=product_id,
            service_name=first.service_name,
            model=FareModel.FLAT,
            status=FareStatus.EXACT,
            estimated_amount=first.fare,
            min_amount=first.fare,
            max_amount=first.fare,
        )
    if isinstance(rule, FlatFareRule):
        return _component(first, rule, FareStatus.EXACT, rule.amount, rule.amount, rule.amount)
    if isinstance(rule, OdMatrixFareRule):
        fare = rule.fares.get((first.from_stop_id, ride[-1].to_stop_id))
        if fare is None:
            return _component(first, rule, FareStatus.UNKNOWN, 0, 0, 0)
        return _component(first, rule, FareStatus.EXACT, fare, fare, fare)
    if isinstance(rule, DistanceBandFareRule):
        distance = sum(_segment_distance_km(segment) for segment in ride)
        extra_bands = max(0, ceil((distance - rule.base_distance_km) / rule.band_distance_km))
        fare = rule.base_amount + extra_bands * rule.band_amount
        return _component(first, rule, FareStatus.ESTIMATED, fare, fare, fare)
    return _component(
        first,
        rule,
        FareStatus.RANGE,
        rule.estimated_amount,
        rule.min_amount,
        rule.max_amount,
    )


def _component(
    segment: Segment,
    rule: FareRule,
    status: FareStatus,
    estimated_amount: int,
    min_amount: int,
    max_amount: int,
) -> FareComponent:
    return FareComponent(
        fare_product_id=rule.product_id,
        service_name=segment.service_name,
        model=rule.model,
        status=status,
        estimated_amount=estimated_amount,
        min_amount=min_amount,
        max_amount=max_amount,
        source_url=rule.source_url,
    )


def _segment_distance_km(segment: Segment) -> float:
    from math import asin, cos, radians, sin, sqrt

    distance = 0.0
    for (from_lng, from_lat), (to_lng, to_lat) in zip(
        segment.coordinates, segment.coordinates[1:], strict=False
    ):
        delta_lat = radians(to_lat - from_lat)
        delta_lng = radians(to_lng - from_lng)
        value = sin(delta_lat / 2) ** 2 + (
            cos(radians(from_lat)) * cos(radians(to_lat)) * sin(delta_lng / 2) ** 2
        )
        distance += 2 * 6371.0088 * asin(sqrt(value))
    return distance


def _combined_status(statuses: set[FareStatus]) -> FareStatus:
    for status in (
        FareStatus.UNKNOWN,
        FareStatus.RANGE,
        FareStatus.ESTIMATED,
        FareStatus.EXACT,
    ):
        if status in statuses:
            return status
    return FareStatus.EXACT
