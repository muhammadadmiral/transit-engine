from fastapi import APIRouter, HTTPException, status

from app.models.schema import RouteSearchRequest, RouteSearchResponse, SearchCriteria, Segment
from app.routing.graph import build_graph
from app.routing.pathfinder import RouteNotFoundError, find_route

router = APIRouter(prefix="/route-search", tags=["route-search"])


def get_segments() -> list[Segment]:
    """Database-backed segment loading will replace this dependency in the ingestion milestone."""
    return []


@router.post("", response_model=RouteSearchResponse)
async def route_search(request: RouteSearchRequest) -> RouteSearchResponse:
    graph = build_graph(get_segments())
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
