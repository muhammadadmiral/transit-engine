"""Queries that translate persistent transit rows into routing domain models."""

import json

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import SegmentRecord, StopRecord
from app.models.schema import Segment, Stop


async def load_segments(session: AsyncSession) -> list[Segment]:
    result = await session.execute(
        select(
            SegmentRecord,
            func.ST_AsGeoJSON(SegmentRecord.geometry).label("geometry_json"),
        )
    )
    return [segment_from_record(record, geometry_json) for record, geometry_json in result.tuples()]


def segment_from_record(record: SegmentRecord, geometry_json: str) -> Segment:
    geometry = json.loads(geometry_json)
    return Segment(
        id=record.id,
        route_id=record.route_id,
        from_stop_id=record.from_stop_id,
        to_stop_id=record.to_stop_id,
        mode=record.mode,
        service_category=record.service_category,
        service_name=record.service_name,
        avg_duration_min=record.avg_duration_min,
        fare=record.fare,
        data_confidence=record.data_confidence,
        last_verified_at=record.last_verified_at,
        color=record.color,
        coordinates=[tuple(point) for point in geometry["coordinates"]],
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
