"""Persist the validated MRT Jakarta and active LRT Jakarta network."""

import asyncio

from app.db.session import SessionLocal
from app.db.transit_writer import replace_dataset, replace_transfer_segments
from app.ingestion.curated.bikun import build_bikun_dataset
from app.ingestion.curated.krl import build_krl_dataset
from app.ingestion.curated.rail import build_rail_dataset
from app.ingestion.curated.transfers import build_transfer_segments
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
        await replace_dataset(session, dataset, {"mrt", "lrt", "krl", "angkot"})
        await replace_transfer_segments(session, await build_transfer_segments(session))
        await session.commit()
    return len(dataset.stops), len(dataset.segments)


def main() -> None:
    stops, segments = asyncio.run(import_rail())
    print(f"Imported {stops} rail stops and {segments} directed rail segments.")


if __name__ == "__main__":
    main()
