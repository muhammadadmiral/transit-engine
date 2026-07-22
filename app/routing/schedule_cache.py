"""Short-lived database cache for scheduled service windows."""

import asyncio
from time import monotonic

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.transit_repository import load_service_frequencies
from app.routing.schedules import ServiceFrequencyIndex

SCHEDULE_CACHE_TTL_SECONDS = 300
_cached_index: ServiceFrequencyIndex | None = None
_cached_at = 0.0
_cache_lock = asyncio.Lock()


async def get_schedule_index(session: AsyncSession) -> ServiceFrequencyIndex:
    global _cached_at, _cached_index
    now = monotonic()
    if _cached_index is not None and now - _cached_at < SCHEDULE_CACHE_TTL_SECONDS:
        return _cached_index
    async with _cache_lock:
        now = monotonic()
        if _cached_index is None or now - _cached_at >= SCHEDULE_CACHE_TTL_SECONDS:
            _cached_index = ServiceFrequencyIndex(await load_service_frequencies(session))
            _cached_at = monotonic()
    return _cached_index


def invalidate_schedule_cache() -> None:
    global _cached_at, _cached_index
    _cached_index = None
    _cached_at = 0.0
