"""Print nearby TransJakarta candidates for manually reviewed rail transfers."""

import argparse
import asyncio

from sqlalchemy import text

from app.db.session import SessionLocal


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args()
    if args.summary:
        async with SessionLocal() as session:
            count = await session.scalar(text("SELECT count(*) FROM segments WHERE mode = 'walk'"))
            pairs = await session.scalar(
                text("SELECT count(DISTINCT route_id) FROM segments WHERE mode = 'walk'")
            )
            geometry_rows = (
                await session.execute(
                    text(
                        "SELECT mode, count(*), min(ST_NPoints(geometry)), "
                        "round(avg(ST_NPoints(geometry))), max(ST_NPoints(geometry)) "
                        "FROM segments WHERE mode IN ('mrt', 'lrt', 'krl', 'walk') "
                        "GROUP BY mode ORDER BY mode"
                    )
                )
            ).fetchall()
        print(f"Walking transfers: {pairs} pairs, {count} directed segments.")
        for row in geometry_rows:
            print(*row, sep="\t")
        return

    statement = text(
        """
        SELECT rail.id, rail.name, candidate.id, candidate.name,
               round(ST_Distance(rail.location::geography, candidate.location::geography))::int
        FROM stops AS rail
        CROSS JOIN LATERAL (
            SELECT id, name, location
            FROM stops AS transit_stop
            WHERE transit_stop.mode = 'transjakarta'
              AND ST_DWithin(rail.location::geography, transit_stop.location::geography, 500)
            ORDER BY rail.location <-> transit_stop.location
            LIMIT 5
        ) AS candidate
        WHERE rail.mode IN ('mrt', 'lrt', 'krl')
        ORDER BY rail.id, ST_Distance(rail.location::geography, candidate.location::geography)
        """
    )
    async with SessionLocal() as session:
        rows = (await session.execute(statement)).fetchall()
    for row in rows:
        print(*row, sep="\t")

    rail_statement = text(
        """
        SELECT first.id, first.name, second.id, second.name,
               round(ST_Distance(first.location::geography, second.location::geography))::int
        FROM stops AS first
        JOIN stops AS second ON first.id < second.id
        WHERE first.mode IN ('mrt', 'lrt', 'krl')
          AND second.mode IN ('mrt', 'lrt', 'krl')
          AND first.mode <> second.mode
          AND ST_DWithin(first.location::geography, second.location::geography, 1000)
        ORDER BY ST_Distance(first.location::geography, second.location::geography)
        """
    )
    async with SessionLocal() as session:
        rail_rows = (await session.execute(rail_statement)).fetchall()
    print("\nRAIL-TO-RAIL")
    for row in rail_rows:
        print(*row, sep="\t")


if __name__ == "__main__":
    asyncio.run(main())
