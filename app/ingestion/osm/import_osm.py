"""CLI to replace the OSM angkot dataset and rebuild walking transfers."""

import asyncio
import logging

from app.db.session import SessionLocal
from app.db.transit_writer import replace_dataset, replace_transfer_segments
from app.ingestion.curated.transfers import build_transfer_segments
from app.ingestion.osm.overpass import fetch_angkot_relations
from app.ingestion.osm.parser import parse_osm_relations

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def import_osm_angkot() -> tuple[int, int]:
    relations = await fetch_angkot_relations()
    if not relations:
        logger.warning("No OSM relations found; existing database data was left untouched.")
        return 0, 0

    dataset = parse_osm_relations(relations)
    if not dataset.stops or not dataset.segments:
        logger.warning("No valid angkot routes parsed; existing database data was left untouched.")
        return 0, 0

    logger.info(
        "Parsed %s virtual stops and %s directed segments",
        len(dataset.stops),
        len(dataset.segments),
    )
    async with SessionLocal() as session:
        await replace_dataset(session, dataset, {"angkot"})
        await replace_transfer_segments(session, await build_transfer_segments(session))
        await session.commit()

    return len(dataset.stops), len(dataset.segments)


if __name__ == "__main__":
    imported_stops, imported_segments = asyncio.run(import_osm_angkot())
    print(f"Imported {imported_stops} OSM angkot stops and {imported_segments} segments.")
