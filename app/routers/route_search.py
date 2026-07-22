from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.db.transit_repository import find_nearby_stops
from app.models.schema import (
    DataConfidence,
    NearbyStop,
    NearbyStopPurpose,
    RouteSearchRequest,
    RouteSearchResponse,
    Segment,
    ServiceCategory,
    TransportMode,
)
from app.routing.geojson_builder import build_feature_collection
from app.routing.graph_cache import get_routing_graph
from app.routing.pathfinder import RouteNotFoundError, find_route_options
from app.routing.pedestrian import get_pedestrian_router
from app.routing.stop_directory import build_stop_directory

router = APIRouter(prefix="/route-search", tags=["route-search"])


@router.post("", response_model=RouteSearchResponse)
async def route_search(
    request: RouteSearchRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RouteSearchResponse:
    try:
        origin_stop_id, origin_access = await _resolve_endpoint(
            session,
            request,
            purpose=NearbyStopPurpose.ORIGIN,
        )
        destination_stop_id, destination_access = await _resolve_endpoint(
            session,
            request,
            purpose=NearbyStopPurpose.DESTINATION,
        )
        graph = await get_routing_graph(session)
    except (OSError, SQLAlchemyError) as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Transit data is temporarily unavailable",
        ) from error

    try:
        options = find_route_options(
            graph,
            origin_stop_id,
            destination_stop_id,
            request.max_transfers,
            request.departure_at,
            request.payment_profile,
            additional_segments=[*origin_access, *destination_access],
        )
    except RouteNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error

    pedestrian_router = get_pedestrian_router()
    for option in options:
        option.segments = await pedestrian_router.enrich_segments(option.segments)
        option.total_duration_min = sum(segment.avg_duration_min for segment in option.segments)
        option.geojson = build_feature_collection(option.segments)

    try:
        referenced_stop_ids: set[str] = set()
        for option in options:
            for segment in option.segments:
                referenced_stop_ids.add(segment.from_stop_id)
                referenced_stop_ids.add(segment.to_stop_id)
        directory = await build_stop_directory(session, referenced_stop_ids)
        for option in options:
            for segment in option.segments:
                from_entry = directory.get(segment.from_stop_id)
                to_entry = directory.get(segment.to_stop_id)
                if from_entry is not None:
                    segment.from_stop_name = from_entry.name
                    segment.from_stop_lat = from_entry.lat
                    segment.from_stop_lng = from_entry.lng
                if to_entry is not None:
                    segment.to_stop_name = to_entry.name
                    segment.to_stop_lat = to_entry.lat
                    segment.to_stop_lng = to_entry.lng
    except (SQLAlchemyError, OSError, AttributeError):
        # Test doubles or DB unavailable — keep raw IDs so response stays valid.
        directory = None
    return RouteSearchResponse(
        origin_stop_id=origin_stop_id,
        destination_stop_id=destination_stop_id,
        options=options,
    )


async def _resolve_endpoint(
    session: AsyncSession,
    request: RouteSearchRequest,
    *,
    purpose: NearbyStopPurpose,
) -> tuple[str, list[Segment]]:
    is_origin = purpose is NearbyStopPurpose.ORIGIN
    stop_id = request.origin_stop_id if is_origin else request.destination_stop_id
    if stop_id is not None:
        return stop_id, []

    lat = request.origin_lat if is_origin else request.destination_lat
    lng = request.origin_lng if is_origin else request.destination_lng
    assert lat is not None and lng is not None  # validated by RouteSearchRequest
    candidates = await find_nearby_stops(
        session,
        lat=lat,
        lng=lng,
        radius_meters=request.access_radius_meters,
        # Dense Mikrotrans corridors can otherwise crowd nearby rail stations
        # out of the candidate set. The pathfinder chooses globally among all
        # candidates instead of blindly snapping to the closest stop.
        limit=32,
        mode=None,
        purpose=purpose,
    )
    if not candidates:
        action = "boardable" if is_origin else "alightable"
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"No {action} transit stop within {request.access_radius_meters} meters "
                f"of {purpose.value}"
            ),
        )

    virtual_id = f"coordinate:{purpose.value}"
    return virtual_id, [
        _access_segment(
            virtual_id=virtual_id,
            pin_lat=lat,
            pin_lng=lng,
            stop=stop,
            is_origin=is_origin,
        )
        for stop in candidates
    ]


def _access_segment(
    *,
    virtual_id: str,
    pin_lat: float,
    pin_lng: float,
    stop: NearbyStop,
    is_origin: bool,
) -> Segment:
    from_stop_id, to_stop_id = (virtual_id, stop.id) if is_origin else (stop.id, virtual_id)
    coordinates = (
        [(pin_lng, pin_lat), (stop.lng, stop.lat)]
        if is_origin
        else [(stop.lng, stop.lat), (pin_lng, pin_lat)]
    )
    direction = "to transit" if is_origin else "to destination"
    return Segment(
        id=f"access:{'origin' if is_origin else 'destination'}:{stop.id}",
        route_id=f"access:{'origin' if is_origin else 'destination'}",
        route_code="WALK",
        route_name=f"Walk {direction}",
        from_stop_id=from_stop_id,
        to_stop_id=to_stop_id,
        mode=TransportMode.WALK,
        service_category=ServiceCategory.TRANSFER,
        service_name=f"Walk {direction}",
        avg_duration_min=round(max(0.5, stop.distance_meters / 75), 1),
        fare=0,
        fare_product_id="free:walk",
        data_confidence=DataConfidence.COMMUNITY,
        last_verified_at=date.today(),
        color="64748B",
        coordinates=coordinates,
    )
