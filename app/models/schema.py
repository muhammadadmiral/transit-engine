from datetime import date
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


class SearchCriteria(StrEnum):
    FASTEST = "fastest"
    CHEAPEST = "cheapest"


class Stop(SchemaModel):
    id: str
    name: str
    lat: Annotated[float, Field(ge=-90, le=90)]
    lng: Annotated[float, Field(ge=-180, le=180)]
    modes: list[TransportMode] = Field(min_length=1)


class Segment(SchemaModel):
    id: str
    from_stop_id: str
    to_stop_id: str
    mode: TransportMode
    avg_duration_min: Annotated[float, Field(gt=0)]
    fare: Annotated[int, Field(ge=0)]
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


class RouteSearchRequest(SchemaModel):
    origin_stop_id: str
    destination_stop_id: str
    max_transfers: Annotated[int, Field(ge=0, le=5)] = 3


class GeoJsonFeature(SchemaModel):
    type: Literal["Feature"] = "Feature"
    geometry: dict[str, object]
    properties: dict[str, object]


class FeatureCollection(SchemaModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[GeoJsonFeature]


class RouteOption(SchemaModel):
    criteria: SearchCriteria
    total_duration_min: float
    total_fare: int
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

