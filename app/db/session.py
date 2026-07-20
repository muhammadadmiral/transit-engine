import socket
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

# Monkey-patch getaddrinfo to force IPv4 for Supabase Connection Pooler
# This prevents uvloop/asyncpg from crashing with ENETUNREACH on IPv6 inside Docker
_original_getaddrinfo = socket.getaddrinfo

def _patched_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    res = _original_getaddrinfo(host, port, family, type, proto, flags)
    if host and "supabase.com" in str(host):
        res = [r for r in res if r[0] == socket.AF_INET]
    return res

socket.getaddrinfo = _patched_getaddrinfo

settings = get_settings()
engine = create_async_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session
