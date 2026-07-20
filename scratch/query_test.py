import asyncio
from sqlalchemy import select, func, cast
from geoalchemy2 import Geography
from sqlalchemy.orm import aliased
from app.db.session import SessionLocal
from app.db.models import StopRecord

async def main():
    async with SessionLocal() as session:
        S1 = aliased(StopRecord)
        S2 = aliased(StopRecord)
        
        # Test if cast to Geography and ST_DWithin works in our DB
        stmt = select(func.count()).select_from(S1).join(
            S2, 
            func.ST_DWithin(
                cast(S1.location, Geography), 
                cast(S2.location, Geography), 
                150
            )
        ).where(S1.id < S2.id)
        
        result = await session.scalar(stmt)
        print(f"Found {result} pairs within 150m")

asyncio.run(main())
