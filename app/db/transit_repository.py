"""Queries that translate persistent transit rows into routing domain models."""

import json

from geoalchemy2 import Geography
from sqlalchemy import case, cast, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import SegmentRecord, StopRecord
from app.models.schema import (
    NearbyStop,
    NearbyStopPurpose,
    RouteOverview,
    Segment,
    Stop,
    TransportMode,
    WalkingRouteSource,
)


async def load_segments(session: AsyncSession) -> list[Segment]:
    result = await session.execute(
        select(
            SegmentRecord,
            func.ST_AsGeoJSON(SegmentRecord.geometry).label("geometry_json"),
        )
    )
    return [segment_from_record(record, geometry_json) for record, geometry_json in result.tuples()]


async def load_route_segments(session: AsyncSession, route_id: str) -> list[Segment]:
    result = await session.execute(
        select(
            SegmentRecord,
            func.ST_AsGeoJSON(SegmentRecord.geometry).label("geometry_json"),
        )
        .where(SegmentRecord.route_id == route_id)
        .order_by(SegmentRecord.id)
    )
    return [segment_from_record(record, geometry_json) for record, geometry_json in result.tuples()]


def segment_from_record(record: SegmentRecord, geometry_json: str) -> Segment:
    geometry = json.loads(geometry_json)
    return Segment(
        id=record.id,
        route_id=record.route_id,
        route_code=record.route_code,
        route_name=record.route_name,
        from_stop_id=record.from_stop_id,
        to_stop_id=record.to_stop_id,
        mode=record.mode,
        service_category=record.service_category,
        service_name=record.service_name,
        avg_duration_min=record.avg_duration_min,
        fare=record.fare,
        fare_product_id=record.fare_product_id,
        data_confidence=record.data_confidence,
        last_verified_at=record.last_verified_at,
        color=record.color,
        coordinates=[tuple(point) for point in geometry["coordinates"]],
        walking_distance_meters=record.walking_distance_meters,
        walking_route_source=(
            WalkingRouteSource(record.walking_route_source) if record.walking_route_source else None
        ),
    )


async def search_stops(session: AsyncSession, query: str, limit: int) -> list[Stop]:
    normalized_query = query.casefold().strip()
    lowered_name = func.lower(StopRecord.name)
    statement = (
        select(
            StopRecord.id,
            StopRecord.name,
            StopRecord.mode,
            func.ST_Y(StopRecord.location).label("lat"),
            func.ST_X(StopRecord.location).label("lng"),
        )
        .where(lowered_name.contains(normalized_query, autoescape=True))
        .order_by(
            case((lowered_name.startswith(normalized_query, autoescape=True), 0), else_=1),
            StopRecord.name,
        )
        .limit(limit)
    )
    result = await session.execute(statement)
    return [
        Stop(id=stop_id, name=name, lat=lat, lng=lng, modes=[mode])
        for stop_id, name, mode, lat, lng in result.tuples()
    ]


async def find_nearby_stops(
    session: AsyncSession,
    *,
    lat: float,
    lng: float,
    radius_meters: int,
    limit: int,
    mode: TransportMode | None,
    purpose: NearbyStopPurpose,
) -> list[NearbyStop]:
    """Return directionally usable stops ordered by geodesic distance."""
    pin = cast(func.ST_SetSRID(func.ST_MakePoint(lng, lat), 4326), Geography(srid=4326))
    stop_location = cast(StopRecord.location, Geography(srid=4326))
    distance = func.ST_Distance(stop_location, pin).label("distance_meters")
    can_board = exists(
        select(SegmentRecord.id).where(
            SegmentRecord.from_stop_id == StopRecord.id,
            SegmentRecord.mode != TransportMode.WALK.value,
        )
    )
    can_alight = exists(
        select(SegmentRecord.id).where(
            SegmentRecord.to_stop_id == StopRecord.id,
            SegmentRecord.mode != TransportMode.WALK.value,
        )
    )
    conditions = [func.ST_DWithin(stop_location, pin, radius_meters)]
    if mode is not None:
        conditions.append(StopRecord.mode == mode.value)
    if purpose is NearbyStopPurpose.ORIGIN:
        conditions.append(can_board)
    elif purpose is NearbyStopPurpose.DESTINATION:
        conditions.append(can_alight)

    statement = (
        select(
            StopRecord.id,
            StopRecord.name,
            StopRecord.mode,
            func.ST_Y(StopRecord.location),
            func.ST_X(StopRecord.location),
            distance,
            can_board.label("can_board"),
            can_alight.label("can_alight"),
        )
        .where(*conditions)
        .order_by(distance, StopRecord.id)
        .limit(limit)
    )
    rows = (await session.execute(statement)).tuples()
    return [
        NearbyStop(
            id=stop_id,
            name=name,
            lat=stop_lat,
            lng=stop_lng,
            modes=[stored_mode],
            distance_meters=round(float(distance_meters), 1),
            can_board=bool(boardable),
            can_alight=bool(alightable),
        )
        for (
            stop_id,
            name,
            stored_mode,
            stop_lat,
            stop_lng,
            distance_meters,
            boardable,
            alightable,
        ) in rows
    ]


async def list_network_stops(
    session: AsyncSession,
    *,
    query: str | None,
    mode: TransportMode | None,
    limit: int,
    offset: int,
) -> tuple[list[Stop], int]:
    conditions = []
    lowered_name = func.lower(StopRecord.name)
    normalized_query = query.casefold().strip() if query else None
    if normalized_query:
        conditions.append(lowered_name.contains(normalized_query, autoescape=True))
    if mode is not None:
        conditions.append(StopRecord.mode == mode.value)

    ordering = (
        (
            case((lowered_name.startswith(normalized_query, autoescape=True), 0), else_=1),
            StopRecord.name,
        )
        if normalized_query
        else (StopRecord.name,)
    )
    statement = (
        select(
            StopRecord.id,
            StopRecord.name,
            StopRecord.mode,
            func.ST_Y(StopRecord.location).label("lat"),
            func.ST_X(StopRecord.location).label("lng"),
        )
        .where(*conditions)
        .order_by(*ordering)
        .offset(offset)
        .limit(limit)
    )
    count_statement = select(func.count()).select_from(StopRecord).where(*conditions)
    result = await session.execute(statement)
    total = await session.scalar(count_statement)
    items = [
        Stop(id=stop_id, name=name, lat=lat, lng=lng, modes=[stored_mode])
        for stop_id, name, stored_mode, lat, lng in result.tuples()
    ]
    return items, int(total or 0)


async def list_route_overviews(
    session: AsyncSession,
    *,
    mode: TransportMode | None,
    limit: int,
    offset: int,
) -> tuple[list[RouteOverview], int]:
    conditions = (
        [SegmentRecord.mode == mode.value]
        if mode is not None
        else [SegmentRecord.mode != TransportMode.WALK.value]
    )
    statement = (
        select(
            SegmentRecord.route_id,
            SegmentRecord.route_code,
            SegmentRecord.mode,
            SegmentRecord.route_name,
            SegmentRecord.color,
            SegmentRecord.service_category,
            func.count().label("segment_count"),
        )
        .where(*conditions)
        .group_by(
            SegmentRecord.route_id,
            SegmentRecord.route_code,
            SegmentRecord.mode,
            SegmentRecord.route_name,
            SegmentRecord.color,
            SegmentRecord.service_category,
        )
        .order_by(SegmentRecord.route_name, SegmentRecord.route_code)
        .offset(offset)
        .limit(limit)
    )
    count_statement = select(func.count(func.distinct(SegmentRecord.route_id))).where(*conditions)
    result = await session.execute(statement)
    total = await session.scalar(count_statement)
    items = []
    for row in result.tuples():
        (
            route_id,
            route_code,
            stored_mode,
            route_name,
            color,
            service_category,
            segment_count,
        ) = row
        items.append(
            RouteOverview(
                id=route_id,
                code=route_code,
                mode=stored_mode,
                name=route_name,
                color=color,
                service_category=service_category,
                segment_count=segment_count,
            )
        )
    return items, int(total or 0)
