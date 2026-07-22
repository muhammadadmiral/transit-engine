"""Short-lived in-process graph cache rebuilt from persistent Supabase data."""

import asyncio
from time import monotonic

import networkx as nx
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.transit_repository import load_all_stops, load_flexible_routes, load_segments
from app.routing.flexible import add_flexible_transfers, materialize_flexible_segments
from app.routing.graph import build_graph
from app.routing.pedestrian import invalidate_pedestrian_cache

GRAPH_CACHE_TTL_SECONDS = 300

_cached_graph: nx.MultiDiGraph | None = None
_cached_at = 0.0
_cache_lock = asyncio.Lock()


async def get_routing_graph(session: AsyncSession) -> nx.MultiDiGraph:
    global _cached_at, _cached_graph

    now = monotonic()
    if _cached_graph is not None and now - _cached_at < GRAPH_CACHE_TTL_SECONDS:
        return _cached_graph

    async with _cache_lock:
        now = monotonic()
        if _cached_graph is not None and now - _cached_at < GRAPH_CACHE_TTL_SECONDS:
            return _cached_graph
        # AsyncSession deliberately disallows concurrent operations on one connection.
        segments = await load_segments(session)
        routes = await load_flexible_routes(session)
        stops = await load_all_stops(session)
        _cached_graph = build_graph([*segments, *materialize_flexible_segments(routes)])
        add_flexible_transfers(_cached_graph, stops)
        _cached_at = monotonic()
        return _cached_graph


def invalidate_graph_cache() -> None:
    global _cached_at, _cached_graph

    _cached_graph = None
    _cached_at = 0.0
    invalidate_pedestrian_cache()
