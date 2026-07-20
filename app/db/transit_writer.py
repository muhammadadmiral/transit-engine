"""Persistence operations for normalized transit datasets."""

from geoalchemy2.elements import WKTElement
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import SegmentRecord, StopRecord
from app.ingestion.gtfs.transjakarta import TransitDataset


async def upsert_transjakarta_dataset(session: AsyncSession, dataset: TransitDataset) -> None:
    """Upsert the latest official TransJakarta stops and directed segments."""
    stop_rows = [
        {
            "id": stop.id,
            "name": stop.name,
            "mode": "transjakarta",
            "location": WKTElement(f"POINT({stop.lng} {stop.lat})", srid=4326),
        }
        for stop in dataset.stops
    ]
    if stop_rows:
        statement = insert(StopRecord).values(stop_rows)
        await session.execute(
            statement.on_conflict_do_update(
                index_elements=[StopRecord.id],
                set_={
                    "name": statement.excluded.name,
                    "mode": statement.excluded.mode,
                    "location": statement.excluded.location,
                },
            )
        )

    segment_rows = [
        {
            "id": segment.id,
            "route_id": segment.route_id,
            "from_stop_id": segment.from_stop_id,
            "to_stop_id": segment.to_stop_id,
            "mode": segment.mode.value,
            "avg_duration_min": segment.avg_duration_min,
            "fare": segment.fare,
            "data_confidence": segment.data_confidence.value,
            "last_verified_at": segment.last_verified_at,
            "color": segment.color,
            "geometry": WKTElement(
                "LINESTRING(" + ", ".join(f"{lng} {lat}" for lng, lat in segment.coordinates) + ")",
                srid=4326,
            ),
        }
        for segment in dataset.segments
    ]
    if segment_rows:
        statement = insert(SegmentRecord).values(segment_rows)
        await session.execute(
            statement.on_conflict_do_update(
                index_elements=[SegmentRecord.id],
                set_={
                    "route_id": statement.excluded.route_id,
                    "avg_duration_min": statement.excluded.avg_duration_min,
                    "fare": statement.excluded.fare,
                    "data_confidence": statement.excluded.data_confidence,
                    "last_verified_at": statement.excluded.last_verified_at,
                    "color": statement.excluded.color,
                    "geometry": statement.excluded.geometry,
                },
            )
        )
