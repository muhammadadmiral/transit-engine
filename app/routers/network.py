"""Read-only network endpoints for map layers and route exploration."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.db.transit_repository import (
    list_network_stops,
    list_route_overviews,
    load_flexible_route_segment,
    load_route_segments,
)
from app.models.schema import (
    FeatureCollection,
    RouteListResponse,
    StopListResponse,
    TransportMode,
)
from app.routing.geojson_builder import build_feature_collection

router = APIRouter(prefix="/network", tags=["network"])


@router.get("/stops", response_model=StopListResponse)
async def network_stops(
    session: Annotated[AsyncSession, Depends(get_session)],
    q: Annotated[str | None, Query(min_length=2, max_length=80)] = None,
    mode: TransportMode | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> StopListResponse:
    try:
        items, total = await list_network_stops(
            session, query=q, mode=mode, limit=limit, offset=offset
        )
    except (OSError, SQLAlchemyError) as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Transit network is temporarily unavailable",
        ) from error
    return StopListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/routes", response_model=RouteListResponse)
async def network_routes(
    session: Annotated[AsyncSession, Depends(get_session)],
    mode: TransportMode | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> RouteListResponse:
    try:
        items, total = await list_route_overviews(session, mode=mode, limit=limit, offset=offset)
    except (OSError, SQLAlchemyError) as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Transit network is temporarily unavailable",
        ) from error
    return RouteListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/routes/{route_id}/geometry", response_model=FeatureCollection)
async def route_geometry(
    route_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FeatureCollection:
    try:
        segments = await load_route_segments(session, route_id)
        if not segments:
            flexible_segment = await load_flexible_route_segment(session, route_id)
            segments = [flexible_segment] if flexible_segment else []
    except (OSError, SQLAlchemyError) as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Transit network is temporarily unavailable",
        ) from error
    if not segments:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Route not found")
    return build_feature_collection(segments)
