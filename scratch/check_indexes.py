import asyncio
from app.db.session import engine
from sqlalchemy import text
async def main():
    async with engine.connect() as conn:
        res = await conn.execute(text("SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'stops';"))
        for row in res:
            print(row)
asyncio.run(main())
