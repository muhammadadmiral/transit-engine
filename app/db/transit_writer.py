"""Persistence operations for normalized transit datasets."""

from geoalchemy2.elements import WKTElement
from sqlalchemy import delete, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    FlexibleRouteRecord,
    SegmentRecord,
    ServiceFrequencyRecord,
    StopRecord,
)
from app.ingestion.gtfs.transjakarta import TransitDataset
from app.models.schema import FlexibleRoute, Segment, ServiceFrequency

WRITE_BATCH_SIZE = 500


async def replace_transjakarta_dataset(session: AsyncSession, dataset: TransitDataset) -> None:
    """Atomically replace official bus and separately classified Mikrotrans data."""
    await replace_dataset(session, dataset, {"transjakarta", "jaklingko"})


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


async def replace_dataset_by_prefix(
    session: AsyncSession,
    dataset: TransitDataset,
    *,
    segment_route_prefix: str,
    stop_id_prefix: str,
) -> None:
    """Replace one namespaced layer while preserving other data of the same mode."""
    await session.execute(delete(SegmentRecord).where(SegmentRecord.mode == "walk"))
    await session.execute(
        delete(SegmentRecord).where(SegmentRecord.route_id.startswith(segment_route_prefix))
    )
    await session.execute(delete(StopRecord).where(StopRecord.id.startswith(stop_id_prefix)))

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


async def replace_flexible_routes(
    session: AsyncSession,
    routes: list[FlexibleRoute],
    *,
    route_id_prefix: str,
) -> None:
    """Replace one corridor namespace and remove obsolete angkot pseudo-stops."""
    await session.execute(
        delete(FlexibleRouteRecord).where(FlexibleRouteRecord.id.startswith(route_id_prefix))
    )
    rows = [
        {
            "id": route.id,
            "route_code": route.route_code,
            "route_name": route.route_name,
            "mode": route.mode.value,
            "service_category": route.service_category.value,
            "service_name": route.service_name,
            "avg_speed_kmh": route.avg_speed_kmh,
            "fare": route.fare,
            "fare_product_id": route.fare_product_id,
            "data_confidence": route.data_confidence.value,
            "last_verified_at": route.last_verified_at,
            "color": route.color,
            "geometry": WKTElement(
                "LINESTRING(" + ", ".join(f"{lng} {lat}" for lng, lat in route.coordinates) + ")",
                srid=4326,
            ),
            "source_url": route.source_url,
        }
        for route in routes
    ]
    for batch in _batches(rows):
        stmt = insert(FlexibleRouteRecord).values(batch)
        stmt = stmt.on_conflict_do_update(
            index_elements=["id"],
            set_={column: getattr(stmt.excluded, column) for column in rows[0] if column != "id"},
        )
        await session.execute(stmt)


async def update_flexible_route_geometry(
    session: AsyncSession,
    route_id: str,
    coordinates: list[tuple[float, float]],
) -> None:
    """Update one reviewed corridor without replacing any route namespace."""
    geometry = WKTElement(
        "LINESTRING(" + ", ".join(f"{lng} {lat}" for lng, lat in coordinates) + ")",
        srid=4326,
    )
    await session.execute(
        update(FlexibleRouteRecord)
        .where(FlexibleRouteRecord.id == route_id)
        .values(geometry=geometry)
    )


async def delete_legacy_angkot_graph(session: AsyncSession) -> None:
    """Delete persisted pseudo-stops only after corridor rows are safely staged."""
    await session.execute(delete(SegmentRecord).where(SegmentRecord.mode == "walk"))
    await session.execute(delete(SegmentRecord).where(SegmentRecord.mode == "angkot"))
    await session.execute(delete(StopRecord).where(StopRecord.mode == "angkot"))


async def replace_service_frequencies(
    session: AsyncSession, frequencies: list[ServiceFrequency]
) -> None:
    modes = {frequency.mode.value for frequency in frequencies}
    if modes:
        await session.execute(
            delete(ServiceFrequencyRecord).where(ServiceFrequencyRecord.mode.in_(modes))
        )
    rows = [
        {
            "id": frequency.id,
            "route_id": frequency.route_id,
            "mode": frequency.mode.value,
            "day_type": frequency.day_type,
            "start_minute": frequency.start_minute,
            "end_minute": frequency.end_minute,
            "headway_min": frequency.headway_min,
            "source_url": frequency.source_url,
            "last_verified_at": frequency.last_verified_at,
        }
        for frequency in frequencies
    ]
    for batch in _batches(rows):
        await session.execute(insert(ServiceFrequencyRecord).values(batch))


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
            "walking_distance_meters": segment.walking_distance_meters,
            "walking_route_source": (
                segment.walking_route_source.value if segment.walking_route_source else None
            ),
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
