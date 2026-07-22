"""Explicit and name-validated walking connectors between supported transit modes."""

import hashlib
import logging
import re
import unicodedata
from datetime import date
from math import asin, cos, radians, sin, sqrt

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.db.models import StopRecord
from app.models.schema import (
    DataConfidence,
    Segment,
    ServiceCategory,
    TransportMode,
)
from app.routing.pedestrian import PedestrianRouter, get_pedestrian_router

logger = logging.getLogger(__name__)

VERIFIED_AT = date(2026, 7, 20)
MAX_NAMED_TRANSFER_METERS = 350
MAX_EXPLICIT_TRANSFER_METERS = 500
MAX_SPATIAL_TRANSFER_METERS = 250
SPATIAL_CONNECTOR_MODES = {"bikun", "jaklingko"}
SAME_MODE_CONNECTOR_MODES = {"transjakarta", "jaklingko"}
MAX_SAME_MODE_TRANSFER_METERS = 120

RAIL_TRANSFERS = (
    ("krl:cawang", "lrt-jabodebek:cikoko"),
    ("krl:sudirman", "mrt:dukuh-atas"),
    ("krl:sudirman", "lrt-jabodebek:dukuh-atas"),
    ("mrt:dukuh-atas", "lrt-jabodebek:dukuh-atas"),
    ("krl:universitas-indonesia", "bikun:stasiun-ui"),
)

TRANSJAKARTA_ALIASES = {
    "krl:batu-ceper": ("term poris plawad",),
    "krl:jurangmangu": ("bintaro xchange",),
    "krl:palmerah": ("ps palmerah",),
    "krl:pasar-senen": ("term senen",),
    "mrt:asean": ("csw 1",),
    "mrt:bendungan-hilir": ("karet sudirman",),
    "mrt:dukuh-atas": ("tosari", "transport hub dukuh atas"),
    "mrt:istora": ("gbk pintu 7", "polda metro jaya"),
    "mrt:senayan": ("bundaran senayan",),
    "lrt-jakarta:velodrome": ("pemuda rawamangun",),
    "lrt-jabodebek:dukuh-atas": ("galunggung", "transport hub dukuh atas"),
    "lrt-jabodebek:halim": ("st kereta cepat halim",),
    "lrt-jabodebek:taman-mini": ("tamini square",),
    "lrt-jabodebek:kampung-rambutan": ("term kampung rambutan",),
}


async def build_transfer_segments(
    session: AsyncSession,
    *,
    pedestrian_router: PedestrianRouter | None = None,
) -> list[Segment]:
    rows = (
        await session.execute(
            select(
                StopRecord.id,
                StopRecord.name,
                StopRecord.mode,
                func.ST_Y(StopRecord.location),
                func.ST_X(StopRecord.location),
            ).where(
                StopRecord.mode.in_(("mrt", "lrt", "krl", "transjakarta", "jaklingko", "bikun"))
            )
        )
    ).tuples()
    stops = {
        stop_id: (name, mode, float(lat), float(lng)) for stop_id, name, mode, lat, lng in rows
    }
    pairs = set()
    for first_id, second_id in RAIL_TRANSFERS:
        if first_id in stops and second_id in stops:
            pairs.add(tuple(sorted((first_id, second_id))))

    rail_stops = {key: value for key, value in stops.items() if value[1] in {"mrt", "lrt", "krl"}}
    transjakarta_stops = {
        key: value for key, value in stops.items() if value[1] in {"transjakarta", "jaklingko"}
    }
    for rail_id, rail in rail_stops.items():
        for transit_id, transit in transjakarta_stops.items():
            distance_meters = _distance_meters(rail[2], rail[3], transit[2], transit[3])
            if _is_valid_transjakarta_transfer(rail_id, rail[0], transit[0], distance_meters):
                pairs.add(tuple(sorted((rail_id, transit_id))))

    first = aliased(StopRecord)
    second = aliased(StopRecord)
    spatial_query = (
        select(first.id, second.id)
        .join(
            second,
            func.ST_DWithin(
                first.location,
                second.location,
                0.002245,  # roughly 250m in degrees at equator
            ),
        )
        .where(
            first.id < second.id,
            or_(
                and_(
                    first.mode != second.mode,
                    or_(
                        first.mode.in_(SPATIAL_CONNECTOR_MODES),
                        second.mode.in_(SPATIAL_CONNECTOR_MODES),
                    ),
                ),
                and_(
                    first.mode == second.mode,
                    first.mode.in_(SAME_MODE_CONNECTOR_MODES),
                ),
            ),
        )
    )
    for first_id, second_id in (await session.execute(spatial_query)).tuples():
        if first_id in stops and second_id in stops:
            first_stop, second_stop = stops[first_id], stops[second_id]
            distance_meters = _distance_meters(
                first_stop[2], first_stop[3], second_stop[2], second_stop[3]
            )
            if _supports_spatial_transfer(
                first_stop[1], second_stop[1], distance_meters=distance_meters
            ):
                pairs.add(tuple(sorted((first_id, second_id))))

    segments = [
        segment
        for first_id, second_id in sorted(pairs)
        for segment in _walking_pair(first_id, second_id, stops[first_id], stops[second_id])
    ]
    router = pedestrian_router or (get_pedestrian_router() if _has_enabled_router() else None)
    if router is not None:
        try:
            segments = await router.enrich_segments(segments)
        except Exception:
            logger.warning("Pedestrian enrichment failed during ingestion; keeping fallback")
    return segments


def _has_enabled_router() -> bool:
    try:
        return bool(get_pedestrian_router().enabled)
    except Exception:
        return False


def _supports_spatial_transfer(
    first_mode: str, second_mode: str, *, distance_meters: float = 0
) -> bool:
    if first_mode == second_mode:
        return (
            first_mode in SAME_MODE_CONNECTOR_MODES
            and distance_meters <= MAX_SAME_MODE_TRANSFER_METERS
        )
    return bool({first_mode, second_mode} & SPATIAL_CONNECTOR_MODES)


def _is_valid_transjakarta_transfer(
    rail_id: str,
    rail_name: str,
    transjakarta_name: str,
    distance_meters: float,
) -> bool:
    candidate = _normalize(transjakarta_name)
    aliases = TRANSJAKARTA_ALIASES.get(rail_id, ())
    if distance_meters <= MAX_EXPLICIT_TRANSFER_METERS and any(
        alias in candidate for alias in aliases
    ):
        return True
    if distance_meters > MAX_NAMED_TRANSFER_METERS:
        return False

    slug = _normalize(rail_id.split(":", maxsplit=1)[1].replace("-", " "))
    display_name = _without_sponsor(_normalize(rail_name))
    return (len(slug) >= 4 and slug in candidate) or (
        len(display_name) >= 4 and display_name in candidate
    )


def _walking_pair(
    first_id: str,
    second_id: str,
    first: tuple[str, str, float, float],
    second: tuple[str, str, float, float],
) -> list[Segment]:
    distance_meters = _distance_meters(first[2], first[3], second[2], second[3])
    duration_min = round(max(2, distance_meters / 75 + 2), 1)
    digest = hashlib.sha1(f"{first_id}|{second_id}".encode(), usedforsecurity=False).hexdigest()[
        :16
    ]
    route_id = f"transfer:{digest}"
    return [
        _walking_segment(
            route_id,
            f"{route_id}:a",
            first_id,
            second_id,
            first,
            second,
            duration_min,
        ),
        _walking_segment(
            route_id,
            f"{route_id}:b",
            second_id,
            first_id,
            second,
            first,
            duration_min,
        ),
    ]


def _walking_segment(
    route_id: str,
    segment_id: str,
    from_stop_id: str,
    to_stop_id: str,
    from_stop: tuple[str, str, float, float],
    to_stop: tuple[str, str, float, float],
    duration_min: float,
) -> Segment:
    return Segment(
        id=segment_id,
        route_id=route_id,
        from_stop_id=from_stop_id,
        to_stop_id=to_stop_id,
        mode=TransportMode.WALK,
        service_category=ServiceCategory.TRANSFER,
        service_name="Walking transfer",
        avg_duration_min=duration_min,
        fare=0,
        fare_product_id="free:walk",
        data_confidence=DataConfidence.COMMUNITY,
        last_verified_at=VERIFIED_AT,
        color="64748B",
        coordinates=[(from_stop[3], from_stop[2]), (to_stop[3], to_stop[2])],
    )


def _without_sponsor(value: str) -> str:
    sponsors = {
        "astra",
        "bank bjb",
        "bank dki",
        "bca",
        "bni",
        "bsi",
        "indomaret",
        "mandiri",
        "mastercard",
    }
    for sponsor in sponsors:
        value = value.replace(sponsor, "")
    return " ".join(value.split())


def _normalize(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", normalized.casefold()).strip()


def _distance_meters(from_lat: float, from_lng: float, to_lat: float, to_lng: float) -> float:
    delta_lat = radians(to_lat - from_lat)
    delta_lng = radians(to_lng - from_lng)
    value = sin(delta_lat / 2) ** 2 + (
        cos(radians(from_lat)) * cos(radians(to_lat)) * sin(delta_lng / 2) ** 2
    )
    return 2 * 6_371_008.8 * asin(sqrt(value))
