"""List actual KRL stop IDs from DB so smoke cases reference real ones."""
import asyncio
import os

from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

load_dotenv("/Users/admiral/Projects/transhub/transit-engine/.env")

PHRASES = [
    "bogor", "cilebut", "bojong", "citayam", "depok", "pondok",
    "bogor", "sawangan", "cimanggis", "bintaro", "lebak",
    "bekasi", "tambun", "cikarang", "tangerang", "tanah",
    "rawa", "sudimara", "palmerah", "karet", "duri",
    "jak", "lebak", "manggarai",
    # MRT
    "blok-m", "fatmawati", "setiabudi", "dukuh",
    # Mikrotrans corridors that might satisfy Cimanggis/Bintaro
    "mikrotrans", "angkot", "lebak",
]


async def main() -> None:
    url = os.environ["DATABASE_URL"].split("?")[0]
    if "+asyncpg" not in url:
        url = url.replace("postgresql://", "postgresql+asyncpg://")
    engine = create_async_engine(url)
    async with engine.connect() as conn:
        for phrase in ["bogo", "depok", "cilebut", "bojonggede", "bojong-gede",
                       "pondok", "citayam", "bintaro", "bekasi", "tangerang",
                       "rawa-buntu", "sudimara", "lebak-bulus", "cikarang",
                       "tanah-tinggi", "tanah-abang", "citayam", "cimanggis",
                       "sawangan", "pancasan", "bogor-pakuan", "cileungsi"]:
            rows = (await conn.execute(text("""
                SELECT id, name, mode FROM stops
                WHERE id ILIKE :pattern OR name ILIKE :pattern
                ORDER BY mode, name LIMIT 8
            """), {"pattern": f"%{phrase}%"})).fetchall()
            if rows:
                print(f"--- {phrase} ---")
                for r in rows:
                    print(f"  {r.mode:14s} {r.id:40s} {r.name}")
    await engine.dispose()


asyncio.run(main())
