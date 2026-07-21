"""Persistence operations for normalized transit datasets."""

from geoalchemy2.elements import WKTElement
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import SegmentRecord, StopRecord
from app.ingestion.gtfs.transjakarta import TransitDataset
from app.models.schema import Segment

WRITE_BATCH_SIZE = 500


async def replace_transjakarta_dataset(session: AsyncSession, dataset: TransitDataset) -> None:
    """Atomically replace official TransJakarta stops and directed segments."""
    await replace_dataset(session, dataset, {"transjakarta"})


async def replace_dataset(session: AsyncSession, dataset: TransitDataset, modes: set[str]) -> None:
    """Atomically replace a validated dataset for one or more isolated modes."""
    await session.execute(delete(SegmentRecord).where(SegmentRecord.mode == "walk"))
    await session.execute(delete(SegmentRecord).where(SegmentRecord.mode.in_(modes)))
    await session.execute(delete(StopRecord).where(StopRecord.mode.in_(modes)))

    stop_rows = [
        {
            "id": stop.id,
            "name": stop.name,
            "mode": stop.modes[0].value,
            "location": WKTElement(f"POINT({stop.lng} {stop.lat})", srid=4326),
        }
        for stop in dataset.stops
    ]
    for batch in _batches(stop_rows):
        stmt = insert(StopRecord).values(batch)
        stmt = stmt.on_conflict_do_update(
            index_elements=["id"],
            set_={
                "name": stmt.excluded.name,
                "mode": stmt.excluded.mode,
                "location": stmt.excluded.location,
            },
        )
        await session.execute(stmt)

    await insert_segments(session, dataset.segments)


async def replace_transfer_segments(session: AsyncSession, segments: list[Segment]) -> None:
    await session.execute(delete(SegmentRecord).where(SegmentRecord.mode == "walk"))
    await insert_segments(session, segments)


async def insert_segments(session: AsyncSession, segments: list[Segment]) -> None:
    segment_rows = [
        {
            "id": segment.id,
            "route_id": segment.route_id,
            "route_code": segment.route_code,
            "route_name": segment.route_name,
            "from_stop_id": segment.from_stop_id,
            "to_stop_id": segment.to_stop_id,
            "mode": segment.mode.value,
            "service_category": segment.service_category.value,
            "service_name": segment.service_name,
            "avg_duration_min": segment.avg_duration_min,
            "fare": segment.fare,
            "fare_product_id": segment.fare_product_id,
            "data_confidence": segment.data_confidence.value,
            "last_verified_at": segment.last_verified_at,
            "color": segment.color,
            "geometry": WKTElement(
                "LINESTRING(" + ", ".join(f"{lng} {lat}" for lng, lat in segment.coordinates) + ")",
                srid=4326,
            ),
        }
        for segment in segments
    ]
    for batch in _batches(segment_rows):
        stmt = insert(SegmentRecord).values(batch)
        stmt = stmt.on_conflict_do_update(
            index_elements=["id"],
            set_={
                "route_id": stmt.excluded.route_id,
                "route_code": stmt.excluded.route_code,
                "route_name": stmt.excluded.route_name,
                "from_stop_id": stmt.excluded.from_stop_id,
                "to_stop_id": stmt.excluded.to_stop_id,
                "mode": stmt.excluded.mode,
                "service_category": stmt.excluded.service_category,
                "service_name": stmt.excluded.service_name,
                "avg_duration_min": stmt.excluded.avg_duration_min,
                "fare": stmt.excluded.fare,
                "fare_product_id": stmt.excluded.fare_product_id,
                "data_confidence": stmt.excluded.data_confidence,
                "last_verified_at": stmt.excluded.last_verified_at,
                "color": stmt.excluded.color,
                "geometry": stmt.excluded.geometry,
            },
        )
        await session.execute(stmt)


def _batches(rows: list[dict[str, object]]) -> list[list[dict[str, object]]]:
    return [
        rows[index : index + WRITE_BATCH_SIZE] for index in range(0, len(rows), WRITE_BATCH_SIZE)
    ]
