from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.db.transit_repository import load_segments
from app.models.schema import RouteSearchRequest, RouteSearchResponse, SearchCriteria, Segment
from app.routing.graph import build_graph
from app.routing.pathfinder import RouteNotFoundError, find_route

router = APIRouter(prefix="/route-search", tags=["route-search"])

@router.post("", response_model=RouteSearchResponse)
async def route_search(
    request: RouteSearchRequest, session: AsyncSession = Depends(get_session)
) -> RouteSearchResponse:
    try:
        segments = await load_segments(session)
    except SQLAlchemyError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Transit data is temporarily unavailable",
        ) from error

    graph = build_graph(segments)
    try:
        options = [
            find_route(
                graph,
                request.origin_stop_id,
                request.destination_stop_id,
                criteria,
                request.max_transfers,
            )
            for criteria in (SearchCriteria.FASTEST, SearchCriteria.CHEAPEST)
        ]
    except RouteNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    return RouteSearchResponse(
        origin_stop_id=request.origin_stop_id,
        destination_stop_id=request.destination_stop_id,
        options=options,
    )
