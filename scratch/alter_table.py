import asyncio
from sqlalchemy import text
from app.db.session import engine

async def alter():
    async with engine.begin() as conn:
        await conn.execute(text("ALTER TABLE segments ALTER COLUMN service_name TYPE VARCHAR(255);"))
        print("Successfully altered table!")

asyncio.run(alter())
