"""Queries that translate persistent transit rows into routing domain models."""

import json

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import SegmentRecord
from app.models.schema import Segment


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
        avg_duration_min=record.avg_duration_min,
        fare=record.fare,
        data_confidence=record.data_confidence,
        last_verified_at=record.last_verified_at,
        color=record.color,
        coordinates=[tuple(point) for point in geometry["coordinates"]],
    )
