"""CLI to replace the OSM angkot dataset and rebuild walking transfers."""

import asyncio
import logging

from app.db.session import SessionLocal
from app.db.transit_writer import (
    delete_legacy_angkot_graph,
    replace_flexible_routes,
)
from app.ingestion.osm.overpass import fetch_angkot_relations
from app.ingestion.osm.parser import parse_osm_relations

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def import_osm_angkot() -> tuple[int, int]:
    relations = await fetch_angkot_relations()
    if not relations:
        logger.warning("No OSM relations found; existing database data was left untouched.")
        return 0, 0
    routes = parse_osm_relations(relations)
    if not routes:
        logger.warning("No valid angkot routes parsed; existing database data was left untouched.")
        return 0, 0

    logger.info("Parsed %s flexible angkot corridors", len(routes))
    async with SessionLocal() as session:
        await replace_flexible_routes(
            session,
            routes,
            route_id_prefix="angkot:osm:",
        )
        await delete_legacy_angkot_graph(session)
        await session.commit()
    return 0, len(routes)


if __name__ == "__main__":
    imported_stops, imported_segments = asyncio.run(import_osm_angkot())
    print(f"Imported {imported_segments} OSM angkot corridors; {imported_stops} fixed stops.")
