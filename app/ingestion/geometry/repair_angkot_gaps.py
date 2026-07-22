"""Repair bounded angkot trace gaps with the configured free OSM road router."""

import argparse
import asyncio
import logging

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.db.transit_repository import load_flexible_routes
from app.db.transit_writer import update_flexible_route_geometry
from app.ingestion.geometry.road_gaps import RoadGapRepairer
from app.routing.graph_cache import invalidate_graph_cache

logger = logging.getLogger(__name__)


async def repair_angkot_gaps(*, apply: bool, prefix: str | None = None) -> tuple[int, int]:
    settings = get_settings()
    repairer = RoadGapRepairer(settings.pedestrian_router_url)
    async with SessionLocal() as session:
        routes = await load_flexible_routes(session)
        routes = [route for route in routes if route.mode.value == "angkot"]
        if prefix:
            routes = [route for route in routes if route.id.startswith(prefix)]
        changed = 0
        for index, route in enumerate(routes, start=1):
            result = await repairer.repair(route.coordinates)
            if result is None:
                logger.warning("[%s/%s] rejected %s", index, len(routes), route.id)
                continue
            if not result.repaired_gaps:
                continue
            changed += 1
            logger.info(
                "[%s/%s] repaired %s gaps in %s",
                index,
                len(routes),
                result.repaired_gaps,
                route.id,
            )
            if apply:
                await update_flexible_route_geometry(session, route.id, result.coordinates)
        if apply:
            await session.commit()
    if apply and changed:
        invalidate_graph_cache()
    return changed, len(routes)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Persist accepted repairs")
    parser.add_argument("--prefix", help="Only process a route ID namespace")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    changed, total = asyncio.run(repair_angkot_gaps(apply=args.apply, prefix=args.prefix))
    action = "updated" if args.apply else "validated (dry run)"
    print(f"{changed}/{total} angkot tracks {action}.")


if __name__ == "__main__":
    main()
