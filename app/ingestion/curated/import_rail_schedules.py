"""Download official rail schedules and persist routing frequency windows."""

import asyncio
import sys
from pathlib import Path

import httpx

from app.db.session import SessionLocal
from app.db.transit_writer import replace_service_frequencies
from app.ingestion.curated.rail_schedules import KRL_SOURCE_URL, build_rail_frequencies
from app.routing.schedule_cache import invalidate_schedule_cache


async def import_rail_schedules(path: str | None = None) -> int:
    if path:
        pdf = Path(path).read_bytes()
    else:
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            response = await client.get(
                KRL_SOURCE_URL, headers={"User-Agent": "TransHub-Jabodetabek/0.1"}
            )
            response.raise_for_status()
            pdf = response.content
    frequencies = build_rail_frequencies(pdf)
    async with SessionLocal() as session:
        await replace_service_frequencies(session, frequencies)
        await session.commit()
    invalidate_schedule_cache()
    return len(frequencies)


if __name__ == "__main__":
    source_path = sys.argv[1] if len(sys.argv) > 1 else None
    count = asyncio.run(import_rail_schedules(source_path))
    print(f"Imported {count} official rail service-frequency windows.")
