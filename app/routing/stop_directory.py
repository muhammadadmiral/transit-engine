"""Stop name and coordinate lookup, used to enrich route segments for the UI."""

from collections.abc import Iterable
from dataclasses import dataclass

from geoalchemy2 import Geography
from sqlalchemy import cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import StopRecord


@dataclass(frozen=True)
class StopSummary:
    id: str
    name: str
    lat: float | None
    lng: float | None


async def build_stop_directory(
    session: AsyncSession,
    stop_ids: Iterable[str],
) -> dict[str, StopSummary]:
    """Return a mapping from stop id to display name and (lat, lng) for any
    referenced stops. Geometry is decoded once per row to avoid round-tripping
    the database for each segment."""
    unique_ids = {stop_id for stop_id in stop_ids if stop_id}
    if not unique_ids:
        return {}
    location = cast(StopRecord.location, Geography(srid=4326))
    statement = select(
        StopRecord.id,
        StopRecord.name,
        func.ST_Y(StopRecord.location).label("lat"),
        func.ST_X(StopRecord.location).label("lng"),
    ).where(StopRecord.id.in_(unique_ids))
    directory: dict[str, StopSummary] = {}
    for stop_id, name, lat, lng in (await session.execute(statement)).tuples():
        directory[stop_id] = StopSummary(
            id=stop_id,
            name=name,
            lat=float(lat) if lat is not None else None,
            lng=float(lng) if lng is not None else None,
        )
    # Silence unused warning so linter doesn't trip if a future change trims it.
    del location
    return directory
