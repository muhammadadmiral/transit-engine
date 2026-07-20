from datetime import date, datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


def to_camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(part.capitalize() for part in tail)


class SchemaModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class TransportMode(StrEnum):
    KRL = "krl"
    MRT = "mrt"
    LRT = "lrt"
    TRANSJAKARTA = "transjakarta"
    ANGKOT = "angkot"


class DataConfidence(StrEnum):
    OFFICIAL = "official"
    COMMUNITY = "community"


class ServiceCategory(StrEnum):
    MAIN = "main"
    FEEDER = "feeder"
    MICROTRANS = "microtrans"
    REGIONAL = "regional"
    PREMIUM = "premium"
    SHUTTLE = "shuttle"
    TOURIST = "tourist"


class SearchCriteria(StrEnum):
    FASTEST = "fastest"
    CHEAPEST = "cheapest"


class FareStatus(StrEnum):
    EXACT = "exact"
    ESTIMATED = "estimated"
    RANGE = "range"
    UNKNOWN = "unknown"


class FareModel(StrEnum):
    FLAT = "flat"
    OD_MATRIX = "od_matrix"
    DISTANCE_BANDS = "distance_bands"
    TIME_DISTANCE_CAP = "time_distance_cap"
    ESTIMATED_RANGE = "estimated_range"


class PaymentProfile(StrEnum):
    STANDARD = "standard"
    JAKLINGKO_INTEGRATED = "jaklingko_integrated"


class Stop(SchemaModel):
    id: str
    name: str
    lat: Annotated[float, Field(ge=-90, le=90)]
    lng: Annotated[float, Field(ge=-180, le=180)]
    modes: list[TransportMode] = Field(min_length=1)


class StopListResponse(SchemaModel):
    items: list[Stop]
    total: Annotated[int, Field(ge=0)]
    limit: Annotated[int, Field(ge=1)]
    offset: Annotated[int, Field(ge=0)]


class Segment(SchemaModel):
    id: str
    route_id: str
    from_stop_id: str
    to_stop_id: str
    mode: TransportMode
    service_category: ServiceCategory
    service_name: str
    avg_duration_min: Annotated[float, Field(gt=0)]
    fare: Annotated[int, Field(ge=0)]
    fare_product_id: str | None = None
    data_confidence: DataConfidence
    last_verified_at: date
    color: str = Field(pattern=r"^[0-9A-Fa-f]{6}$")
    coordinates: list[tuple[float, float]] = Field(min_length=2)


class Route(SchemaModel):
    id: str
    mode: TransportMode
    name: str
    color: str = Field(pattern=r"^[0-9A-Fa-f]{6}$")
    stop_ids: list[str] = Field(min_length=2)


class RouteOverview(SchemaModel):
    id: str
    mode: TransportMode
    name: str
    color: str = Field(pattern=r"^[0-9A-Fa-f]{6}$")
    service_category: ServiceCategory
    segment_count: Annotated[int, Field(ge=1)]


class RouteListResponse(SchemaModel):
    items: list[RouteOverview]
    total: Annotated[int, Field(ge=0)]
    limit: Annotated[int, Field(ge=1)]
    offset: Annotated[int, Field(ge=0)]


class RouteSearchRequest(SchemaModel):
    origin_stop_id: str
    destination_stop_id: str
    max_transfers: Annotated[int, Field(ge=0, le=5)] = 3
    departure_at: datetime | None = None
    payment_profile: PaymentProfile = PaymentProfile.STANDARD


class GeoJsonFeature(SchemaModel):
    type: Literal["Feature"] = "Feature"
    geometry: dict[str, object]
    properties: dict[str, object]


class FeatureCollection(SchemaModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[GeoJsonFeature]


class FareComponent(SchemaModel):
    fare_product_id: str
    service_name: str
    model: FareModel
    status: FareStatus
    estimated_amount: Annotated[int, Field(ge=0)]
    min_amount: Annotated[int, Field(ge=0)]
    max_amount: Annotated[int, Field(ge=0)]
    source_url: str | None = None


class FareQuote(SchemaModel):
    currency: Literal["IDR"] = "IDR"
    status: FareStatus
    estimated_amount: Annotated[int, Field(ge=0)]
    min_amount: Annotated[int, Field(ge=0)]
    max_amount: Annotated[int, Field(ge=0)]
    payment_profile: PaymentProfile
    components: list[FareComponent]
    assumptions: list[str] = Field(default_factory=list)


class RouteOption(SchemaModel):
    criteria: SearchCriteria
    total_duration_min: float
    total_fare: int
    fare_quote: FareQuote
    transfer_count: int
    segments: list[Segment]
    geojson: FeatureCollection


class RouteSearchResponse(SchemaModel):
    origin_stop_id: str
    destination_stop_id: str
    options: list[RouteOption]


class HealthResponse(SchemaModel):
    status: Literal["ok"] = "ok"
    environment: str


class DataRefreshResponse(SchemaModel):
    source: str
    stops_imported: int
    segments_imported: int
