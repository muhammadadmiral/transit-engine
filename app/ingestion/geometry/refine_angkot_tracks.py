"""Refine persisted angkot traces against the road network using TomTom."""

import argparse
import asyncio
import logging

from app.db.session import SessionLocal
from app.db.transit_repository import load_flexible_routes
from app.db.transit_writer import update_flexible_route_geometry
from app.ingestion.geometry.tomtom import TomTomRoadSnapper
from app.routing.graph_cache import invalidate_graph_cache

logger = logging.getLogger(__name__)


async def refine_angkot_tracks(*, apply: bool, prefix: str | None = None) -> tuple[int, int]:
    snapper = TomTomRoadSnapper()
    if not snapper.enabled:
        raise RuntimeError("Set TOMTOM_API_KEY before refining tracks")
    async with SessionLocal() as session:
        routes = await load_flexible_routes(session)
        routes = [route for route in routes if route.mode.value == "angkot"]
        if prefix:
            routes = [route for route in routes if route.id.startswith(prefix)]
        accepted = 0
        for index, route in enumerate(routes, start=1):
            snapped = await snapper.snap(route.coordinates)
            if snapped is None:
                logger.warning("[%s/%s] rejected %s", index, len(routes), route.id)
                continue
            accepted += 1
            logger.info("[%s/%s] refined %s", index, len(routes), route.id)
            if apply:
                await update_flexible_route_geometry(session, route.id, snapped)
        if apply:
            await session.commit()
    if apply and accepted:
        invalidate_graph_cache()
    return accepted, len(routes)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Persist accepted geometry updates")
    parser.add_argument("--prefix", help="Only process a route ID namespace")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    accepted, total = asyncio.run(refine_angkot_tracks(apply=args.apply, prefix=args.prefix))
    action = "updated" if args.apply else "validated (dry run)"
    print(f"{accepted}/{total} angkot tracks {action}.")


if __name__ == "__main__":
    main()
