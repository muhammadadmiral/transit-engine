from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.models.schema import RouteSearchRequest, RouteSearchResponse, SearchCriteria
from app.routing.graph_cache import get_routing_graph
from app.routing.pathfinder import RouteNotFoundError, find_route

router = APIRouter(prefix="/route-search", tags=["route-search"])


@router.post("", response_model=RouteSearchResponse)
async def route_search(
    request: RouteSearchRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RouteSearchResponse:
    try:
        graph = await get_routing_graph(session)
    except SQLAlchemyError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Transit data is temporarily unavailable",
        ) from error

    try:
        options = [
            find_route(
                graph,
                request.origin_stop_id,
                request.destination_stop_id,
                criteria,
                request.max_transfers,
                request.departure_at,
                request.payment_profile,
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
