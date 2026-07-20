import logging
import socket
import urllib.parse
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


def _prefer_ipv4_for_supabase(database_url: str) -> str:
    """Prefer Supabase IPv4 without making app import depend on live DNS."""
    parsed_url = urllib.parse.urlparse(database_url)
    hostname = parsed_url.hostname
    if not hostname or "supabase.com" not in hostname:
        return database_url
    try:
        ipv4_address = socket.gethostbyname(hostname)
    except socket.gaierror:
        logger.warning("Could not pre-resolve Supabase hostname; using configured hostname")
        return database_url
    netloc = parsed_url.netloc.replace(hostname, ipv4_address)
    return urllib.parse.urlunparse(parsed_url._replace(netloc=netloc))


db_url = _prefer_ipv4_for_supabase(settings.database_url)

engine = create_async_engine(db_url, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session
