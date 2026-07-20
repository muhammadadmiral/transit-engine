import socket
import urllib.parse
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

settings = get_settings()
db_url = settings.database_url

# Force IPv4 for Supabase Connection Pooler because uvloop's DNS resolver 
# sometimes defaults to IPv6 inside Docker which causes ENETUNREACH.
parsed_url = urllib.parse.urlparse(db_url)
if parsed_url.hostname and "supabase.com" in parsed_url.hostname:
    ip_v4 = socket.gethostbyname(parsed_url.hostname)
    # Replace the hostname with the resolved IPv4 address
    netloc = parsed_url.netloc.replace(parsed_url.hostname, ip_v4)
    parsed_url = parsed_url._replace(netloc=netloc)
    db_url = urllib.parse.urlunparse(parsed_url)

engine = create_async_engine(db_url, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session
