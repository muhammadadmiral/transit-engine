"""Queries that translate persistent transit rows into routing domain models."""

import json

from geoalchemy2 import Geography
from sqlalchemy import case, cast, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    FlexibleRouteRecord,
    SegmentRecord,
    ServiceFrequencyRecord,
    StopRecord,
)
from app.models.schema import (
    DataConfidence,
    FlexibleRoute,
    NearbyStop,
    NearbyStopPurpose,
    RouteOverview,
    Segment,
    ServiceFrequency,
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


async def load_flexible_routes(session: AsyncSession) -> list[FlexibleRoute]:
    result = await session.execute(
        select(
            FlexibleRouteRecord,
            func.ST_AsGeoJSON(FlexibleRouteRecord.geometry).label("geometry_json"),
        ).order_by(FlexibleRouteRecord.id)
    )
    routes = []
    for record, geometry_json in result.tuples():
        geometry = json.loads(geometry_json)
        routes.append(
            FlexibleRoute(
                id=record.id,
                route_code=record.route_code,
                route_name=record.route_name,
                mode=record.mode,
                service_category=record.service_category,
                service_name=record.service_name,
                avg_speed_kmh=record.avg_speed_kmh,
                fare=record.fare,
                fare_product_id=record.fare_product_id,
                data_confidence=record.data_confidence,
                last_verified_at=record.last_verified_at,
                color=record.color,
                coordinates=[tuple(point) for point in geometry["coordinates"]],
                source_url=record.source_url,
            )
        )
    return routes


async def load_all_stops(session: AsyncSession) -> list[Stop]:
    result = await session.execute(
        select(
            StopRecord.id,
            StopRecord.name,
            StopRecord.mode,
            func.ST_Y(StopRecord.location),
            func.ST_X(StopRecord.location),
        )
    )
    return [
        Stop(id=stop_id, name=name, modes=[mode], lat=float(lat), lng=float(lng))
        for stop_id, name, mode, lat, lng in result.tuples()
    ]


async def load_service_frequencies(session: AsyncSession) -> list[ServiceFrequency]:
    rows = (await session.execute(select(ServiceFrequencyRecord))).scalars()
    return [
        ServiceFrequency(
            id=row.id,
            route_id=row.route_id,
            mode=row.mode,
            day_type=row.day_type,
            start_minute=row.start_minute,
            end_minute=row.end_minute,
            headway_min=row.headway_min,
            source_url=row.source_url,
            last_verified_at=row.last_verified_at,
        )
        for row in rows
    ]


async def load_flexible_route_segment(session: AsyncSession, route_id: str) -> Segment | None:
    result = await session.execute(
        select(
            FlexibleRouteRecord,
            func.ST_AsGeoJSON(FlexibleRouteRecord.geometry).label("geometry_json"),
        ).where(FlexibleRouteRecord.id == route_id)
    )
    row = result.tuples().first()
    if row is None:
        return None
    record, geometry_json = row
    coordinates = [tuple(point) for point in json.loads(geometry_json)["coordinates"]]
    return Segment(
        id=f"{record.id}:geometry",
        route_id=record.id,
        route_code=record.route_code,
        route_name=record.route_name,
        from_stop_id=f"{record.id}:start",
        to_stop_id=f"{record.id}:end",
        mode=record.mode,
        service_category=record.service_category,
        service_name=record.service_name,
        avg_duration_min=1,
        fare=record.fare,
        fare_product_id=record.fare_product_id,
        data_confidence=DataConfidence(record.data_confidence),
        last_verified_at=record.last_verified_at,
        color=record.color,
        coordinates=coordinates,
    )


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
    segment_conditions = (
        [SegmentRecord.mode == mode.value]
        if mode is not None
        else [SegmentRecord.mode != TransportMode.WALK.value]
    )
    segment_statement = (
        select(
            SegmentRecord.route_id,
            SegmentRecord.route_code,
            SegmentRecord.mode,
            SegmentRecord.route_name,
            SegmentRecord.color,
            SegmentRecord.service_category,
            func.count().label("segment_count"),
        )
        .where(*segment_conditions)
        .group_by(
            SegmentRecord.route_id,
            SegmentRecord.route_code,
            SegmentRecord.mode,
            SegmentRecord.route_name,
            SegmentRecord.color,
            SegmentRecord.service_category,
        )
    )
    items: list[RouteOverview] = []
    for row in (await session.execute(segment_statement)).tuples():
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

    flexible_conditions = [FlexibleRouteRecord.mode == mode.value] if mode is not None else []
    flexible_statement = select(
        FlexibleRouteRecord.id,
        FlexibleRouteRecord.route_code,
        FlexibleRouteRecord.mode,
        FlexibleRouteRecord.route_name,
        FlexibleRouteRecord.color,
        FlexibleRouteRecord.service_category,
    ).where(*flexible_conditions)
    for route_id, code, stored_mode, name, color, category in (
        await session.execute(flexible_statement)
    ).tuples():
        items.append(
            RouteOverview(
                id=route_id,
                code=code,
                mode=stored_mode,
                name=name,
                color=color,
                service_category=category,
                segment_count=1,
            )
        )
    items.sort(key=lambda item: (item.name.casefold(), item.code.casefold(), item.id))
    return items[offset : offset + limit], len(items)
