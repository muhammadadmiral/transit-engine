"""Persist the validated MRT Jakarta and active LRT Jakarta network."""

import asyncio

from app.db.session import SessionLocal
from app.db.transit_writer import replace_dataset
from app.ingestion.curated.rail import build_rail_dataset


async def import_rail() -> tuple[int, int]:
    dataset = build_rail_dataset()
    async with SessionLocal() as session:
        await replace_dataset(session, dataset, {"mrt", "lrt"})
        await session.commit()
    return len(dataset.stops), len(dataset.segments)


def main() -> None:
    stops, segments = asyncio.run(import_rail())
    print(f"Imported {stops} rail stops and {segments} directed rail segments.")


if __name__ == "__main__":
    main()
