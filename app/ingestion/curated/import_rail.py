"""Persist curated rail, KRL, Bikun, and their walking transfers."""

import asyncio

from app.db.session import SessionLocal
from app.db.transit_writer import replace_dataset
from app.ingestion.curated.bikun import build_bikun_dataset
from app.ingestion.curated.krl import build_krl_dataset
from app.ingestion.curated.rail import build_rail_dataset
from app.ingestion.gtfs.transjakarta import TransitDataset


async def import_rail() -> tuple[int, int]:
    rapid_transit = build_rail_dataset()
    commuter = build_krl_dataset()
    bikun = build_bikun_dataset()
    dataset = TransitDataset(
        stops=[*rapid_transit.stops, *commuter.stops, *bikun.stops],
        segments=[*rapid_transit.segments, *commuter.segments, *bikun.segments],
    )
    async with SessionLocal() as session:
        await replace_dataset(session, dataset, {"mrt", "lrt", "krl", "bikun"})
        await session.commit()
    return len(dataset.stops), len(dataset.segments)


def main() -> None:
    stops, segments = asyncio.run(import_rail())
    print(f"Imported {stops} curated stops and {segments} directed segments.")


if __name__ == "__main__":
    main()
