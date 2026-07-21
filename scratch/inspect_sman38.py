import asyncio
import os

from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

load_dotenv("/Users/admiral/Projects/transhub/transit-engine/.env")

SMAN38 = (106.8345, -6.3406)  # approx SMAN 38 Jakarta, Lenteng Agung


async def main() -> None:
    url = os.environ["DATABASE_URL"].split("?")[0]
    if "+asyncpg" not in url:
        url = url.replace("postgresql://", "postgresql+asyncpg://")
    engine = create_async_engine(url)
    async with engine.connect() as conn:
        rows = (await conn.execute(text("""
            SELECT id, name, mode,
              ST_Distance(location::geography, ST_SetSRID(ST_MakePoint(:lng, :lat),4326)::geography) AS dist
            FROM stops ORDER BY dist LIMIT 14
        """), {"lng": SMAN38[0], "lat": SMAN38[1]})).fetchall()
        print("=== Stop terdekat dari SMAN 38 ===")
        for r in rows:
            print(f"{r.dist:7.0f}m  {r.id:36s} {r.mode:14s} {r.name}")

        rows = (await conn.execute(text("""
            SELECT id, name, mode,
              ST_Distance(location::geography, ST_SetSRID(ST_MakePoint(:lng, :lat),4326)::geography) AS dist
            FROM stops WHERE mode = 'krl' ORDER BY dist LIMIT 5
        """), {"lng": SMAN38[0], "lat": SMAN38[1]})).fetchall()
        print("\n=== Stasiun KRL terdekat ===")
        for r in rows:
            print(f"{r.dist:7.0f}m  {r.id:36s} {r.name}")

        # Segmen keluar dari halte TJ yang dipakai rute ngaco (B05266P)
        rows = (await conn.execute(text("""
            SELECT s.id, s.route_code, s.mode, s.avg_duration_min, s.fare, s.from_stop_id, s.to_stop_id
            FROM segments s WHERE s.from_stop_id LIKE '%B05266P%' OR s.to_stop_id LIKE '%B05266P%' LIMIT 12
        """))).fetchall()
        print("\n=== Segmen di sekitar B05266P ===")
        for r in rows:
            print(f"{r.mode:14s} {str(r.route_code):10s} {r.avg_duration_min:5.1f}m Rp{r.fare:<6} {r.from_stop_id} -> {r.to_stop_id}")
    await engine.dispose()


asyncio.run(main())
