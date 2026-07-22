"""In-process graph cache rebuilt explicitly after persistent data refreshes."""

import asyncio

import networkx as nx
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.transit_repository import load_all_stops, load_flexible_routes, load_segments
from app.routing.flexible import add_flexible_transfers, materialize_flexible_segments
from app.routing.graph import build_graph
from app.routing.pedestrian import invalidate_pedestrian_cache
from app.routing.transfers import add_sparse_fixed_transfers

_cached_graph: nx.MultiDiGraph | None = None
_cache_lock = asyncio.Lock()


async def get_routing_graph(session: AsyncSession) -> nx.MultiDiGraph:
    global _cached_graph

    if _cached_graph is not None:
        return _cached_graph

    async with _cache_lock:
        if _cached_graph is not None:
            return _cached_graph
        # Walking interchanges are rebuilt sparsely. Loading the legacy fully
        # connected walking layer adds tens of thousands of Pydantic objects.
        segments = await load_segments(session, include_walk=False)
        routes = await load_flexible_routes(session)
        stops = await load_all_stops(session)
        _cached_graph = build_graph([*segments, *materialize_flexible_segments(routes)])
        add_sparse_fixed_transfers(_cached_graph, stops)
        add_flexible_transfers(_cached_graph, stops)
        return _cached_graph


def invalidate_graph_cache() -> None:
    global _cached_graph

    _cached_graph = None
    invalidate_pedestrian_cache()
