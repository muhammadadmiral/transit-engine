"""Persist curated angkot corridors without replacing the OSM layer."""

import asyncio

from app.db.session import SessionLocal
from app.db.transit_writer import (
    delete_legacy_angkot_graph,
    replace_flexible_routes,
    replace_transfer_segments,
)
from app.ingestion.curated.angkot_depok import build_depok_angkot_routes
from app.ingestion.curated.transfers import build_transfer_segments


async def import_curated_angkot() -> tuple[int, int]:
    routes = build_depok_angkot_routes()
    async with SessionLocal() as session:
        await replace_flexible_routes(
            session,
            routes,
            route_id_prefix="angkot:depok:",
        )
        await delete_legacy_angkot_graph(session)
        await replace_transfer_segments(session, await build_transfer_segments(session))
        await session.commit()
    return 0, len(routes)


if __name__ == "__main__":
    imported_stops, imported_segments = asyncio.run(import_curated_angkot())
    print(f"Imported {imported_segments} curated angkot corridors; {imported_stops} fixed stops.")
