"""Persistence operations for normalized transit datasets."""

from geoalchemy2.elements import WKTElement
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import SegmentRecord, StopRecord
from app.ingestion.gtfs.transjakarta import TransitDataset

WRITE_BATCH_SIZE = 500


async def replace_transjakarta_dataset(session: AsyncSession, dataset: TransitDataset) -> None:
    """Atomically replace official TransJakarta stops and directed segments."""
    await session.execute(delete(SegmentRecord).where(SegmentRecord.mode == "transjakarta"))
    await session.execute(delete(StopRecord).where(StopRecord.mode == "transjakarta"))

    stop_rows = [
        {
            "id": stop.id,
            "name": stop.name,
            "mode": "transjakarta",
            "location": WKTElement(f"POINT({stop.lng} {stop.lat})", srid=4326),
        }
        for stop in dataset.stops
    ]
    for batch in _batches(stop_rows):
        await session.execute(insert(StopRecord).values(batch))

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
    for batch in _batches(segment_rows):
        await session.execute(insert(SegmentRecord).values(batch))


def _batches(rows: list[dict[str, object]]) -> list[list[dict[str, object]]]:
    return [
        rows[index : index + WRITE_BATCH_SIZE] for index in range(0, len(rows), WRITE_BATCH_SIZE)
    ]
