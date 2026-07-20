"""Pure fare calculation over complete transit journeys.

Fares intentionally live outside graph edges: a flat boarding fare, an
origin/destination matrix, and a distance band cannot be represented faithfully
by one additive number on every segment.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from math import ceil
from zoneinfo import ZoneInfo

from app.models.schema import (
    FareComponent,
    FareModel,
    FareQuote,
    FareStatus,
    PaymentProfile,
    Segment,
)

JAKLINGKO_ELIGIBLE_PRODUCTS = {
    "transjakarta:regular",
    "mrt-jakarta:regular",
    "lrt-jakarta:regular",
}
JAKLINGKO_SOURCE_URL = "https://jaklingkoindonesia.co.id/faq-tarif-integrasi/"


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


@dataclass(frozen=True)
class TimeDistanceCapFareRule:
    product_id: str
    base_amount: int
    base_distance_km: float
    per_km_amount: int
    offpeak_cap: int
    peak_cap: int
    source_url: str
    model: FareModel = FareModel.TIME_DISTANCE_CAP


FareRule = (
    FlatFareRule
    | OdMatrixFareRule
    | DistanceBandFareRule
    | EstimatedRangeFareRule
    | TimeDistanceCapFareRule
)


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
    if not segments:
        return FareQuote(
            status=FareStatus.EXACT,
            estimated_amount=0,
            min_amount=0,
            max_amount=0,
            payment_profile=payment_profile,
            components=[],
        )

    rides = _fare_rides(segments)
    components = [_quote_ride(ride, catalog, departure_at) for ride in rides]
    assumptions = []
    if payment_profile is PaymentProfile.JAKLINGKO_INTEGRATED:
        components, integrated_assumption = _apply_jaklingko_integrated_fare(
            segments, rides, components
        )
        assumptions.append(integrated_assumption)
    statuses = {component.status for component in components}
    status = _combined_status(statuses)
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


def _quote_ride(
    ride: list[Segment], catalog: FareCatalog, departure_at: datetime | None
) -> FareComponent:
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
    if isinstance(rule, TimeDistanceCapFareRule):
        distance = sum(_segment_distance_km(segment) for segment in ride)
        uncapped = (
            rule.base_amount + max(0, ceil(distance - rule.base_distance_km)) * rule.per_km_amount
        )
        offpeak_fare = min(uncapped, rule.offpeak_cap)
        peak_fare = min(uncapped, rule.peak_cap)
        if departure_at is None and offpeak_fare != peak_fare:
            return _component(
                first,
                rule,
                FareStatus.RANGE,
                offpeak_fare,
                offpeak_fare,
                peak_fare,
            )
        cap = rule.peak_cap if _is_weekday_peak(departure_at) else rule.offpeak_cap
        fare = min(uncapped, cap)
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


def _apply_jaklingko_integrated_fare(
    segments: list[Segment],
    rides: list[list[Segment]],
    components: list[FareComponent],
) -> tuple[list[FareComponent], str]:
    eligible_products = {
        ride[0].fare_product_id
        for ride in rides
        if ride[0].fare_product_id in JAKLINGKO_ELIGIBLE_PRODUCTS
    }
    duration = sum(segment.avg_duration_min for segment in segments)
    if len(eligible_products) < 2 or duration > 180:
        return components, (
            "Standard fares shown because this journey does not contain at least two eligible "
            "JakLingko modes within the modeled 180-minute window."
        )

    eligible_segments = [
        segment for segment in segments if segment.fare_product_id in JAKLINGKO_ELIGIBLE_PRODUCTS
    ]
    distance = sum(_segment_distance_km(segment) for segment in eligible_segments)
    amount = min(2500 + ceil(distance) * 250, 10000)
    remaining = [
        component
        for component in components
        if component.fare_product_id not in JAKLINGKO_ELIGIBLE_PRODUCTS
    ]
    integrated = FareComponent(
        fare_product_id="jaklingko:integrated",
        service_name="JakLingko Integrated Fare",
        model=FareModel.TIME_DISTANCE_CAP,
        status=FareStatus.ESTIMATED,
        estimated_amount=amount,
        min_amount=amount,
        max_amount=amount,
        source_url=JAKLINGKO_SOURCE_URL,
    )
    return [integrated, *remaining], (
        "JakLingko integrated fare assumes an eligible payment channel and completion within "
        "180 minutes; distance is estimated from route geometry."
    )


def _is_weekday_peak(value: datetime | None) -> bool:
    if value is None:
        return False
    if value.tzinfo is None:
        local = value.replace(tzinfo=ZoneInfo("Asia/Jakarta"))
    else:
        local = value.astimezone(ZoneInfo("Asia/Jakarta"))
    if local.weekday() >= 5:
        return False
    minute = local.hour * 60 + local.minute
    return 6 * 60 <= minute <= 8 * 60 + 59 or 16 * 60 <= minute <= 19 * 60 + 59
