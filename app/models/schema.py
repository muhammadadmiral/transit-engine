from datetime import date, datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

_OSM_GENERATED_NAME = "Perhentian "


def normalize_stop_name(name: str, stop_id: str) -> str:
    """Return a human-readable label for a stop. Generated placeholders such as
    'Perhentian 5' or anything that only echoes the OSM identifier is replaced
    with a coordinate hint so the UI can still surface 'Naik di -6.27, 106.72'
    instead of dumping the raw internal ID."""
    cleaned = (name or "").strip()
    if cleaned and not cleaned.startswith(_OSM_GENERATED_NAME) and cleaned != stop_id:
        return cleaned
    if "coordinate" in stop_id:
        return "Titik di peta"
    return cleaned or stop_id


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
    BIKUN = "bikun"
    WALK = "walk"


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
    TRANSFER = "transfer"
    BIKUN = "bikun"


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


class NearbyStopPurpose(StrEnum):
    ANY = "any"
    ORIGIN = "origin"
    DESTINATION = "destination"


class Stop(SchemaModel):
    id: str
    name: str
    lat: Annotated[float, Field(ge=-90, le=90)]
    lng: Annotated[float, Field(ge=-180, le=180)]
    modes: list[TransportMode] = Field(min_length=1)


class NearbyStop(Stop):
    distance_meters: Annotated[float, Field(ge=0)]
    can_board: bool
    can_alight: bool


class StopListResponse(SchemaModel):
    items: list[Stop]
    total: Annotated[int, Field(ge=0)]
    limit: Annotated[int, Field(ge=1)]
    offset: Annotated[int, Field(ge=0)]


class Segment(SchemaModel):
    id: str
    route_id: str
    route_code: str = ""
    route_name: str = ""
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
    from_stop_name: str = ""
    to_stop_name: str = ""
    from_stop_lat: float | None = None
    from_stop_lng: float | None = None
    to_stop_lat: float | None = None
    to_stop_lng: float | None = None

    @model_validator(mode="after")
    def fill_route_display_fields(self) -> "Segment":
        """Keep old constructors/imports compatible while exposing UI-safe labels."""
        if not self.route_code:
            parts = self.route_id.split(":")
            if self.mode is TransportMode.TRANSJAKARTA and len(parts) > 1:
                self.route_code = parts[1]
            elif self.mode is TransportMode.ANGKOT and len(parts) > 3:
                self.route_code = parts[3].upper()
            elif self.mode is TransportMode.WALK:
                self.route_code = "WALK"
            else:
                self.route_code = parts[-1].replace("-", " ").upper()
        if not self.route_name:
            self.route_name = self.service_name
        self.from_stop_name = normalize_stop_name(self.from_stop_name, self.from_stop_id)
        self.to_stop_name = normalize_stop_name(self.to_stop_name, self.to_stop_id)
        return self


class Route(SchemaModel):
    id: str
    mode: TransportMode
    name: str
    color: str = Field(pattern=r"^[0-9A-Fa-f]{6}$")
    stop_ids: list[str] = Field(min_length=2)


class RouteOverview(SchemaModel):
    id: str
    code: str
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
    origin_stop_id: str | None = Field(default=None, min_length=1, max_length=120)
    destination_stop_id: str | None = Field(default=None, min_length=1, max_length=120)
    origin_lat: Annotated[float | None, Field(default=None, ge=-90, le=90)]
    origin_lng: Annotated[float | None, Field(default=None, ge=-180, le=180)]
    destination_lat: Annotated[float | None, Field(default=None, ge=-90, le=90)]
    destination_lng: Annotated[float | None, Field(default=None, ge=-180, le=180)]
    access_radius_meters: Annotated[int, Field(ge=100, le=5000)] = 1500
    max_transfers: Annotated[int, Field(ge=0, le=5)] = 3
    departure_at: datetime | None = None
    payment_profile: PaymentProfile = PaymentProfile.STANDARD

    @model_validator(mode="after")
    def validate_endpoints(self) -> "RouteSearchRequest":
        self._validate_endpoint("origin", self.origin_stop_id, self.origin_lat, self.origin_lng)
        self._validate_endpoint(
            "destination",
            self.destination_stop_id,
            self.destination_lat,
            self.destination_lng,
        )
        return self

    @staticmethod
    def _validate_endpoint(
        label: str, stop_id: str | None, lat: float | None, lng: float | None
    ) -> None:
        has_stop = stop_id is not None
        has_any_coordinate = lat is not None or lng is not None
        has_coordinates = lat is not None and lng is not None
        if has_stop == has_coordinates and not (has_stop and has_any_coordinate):
            raise ValueError(f"{label} must use either stop ID or latitude/longitude")
        if has_stop and has_any_coordinate:
            raise ValueError(f"{label} cannot combine stop ID with latitude/longitude")
        if has_any_coordinate and not has_coordinates:
            raise ValueError(f"{label} latitude and longitude must be provided together")


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
