import asyncio
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
from app.routing.flexible import nearby_flexible_nodes
from app.routing.geojson_builder import build_feature_collection
from app.routing.graph_cache import get_routing_graph
from app.routing.pathfinder import RouteNotFoundError, find_route_options
from app.routing.pedestrian import get_pedestrian_router
from app.routing.schedule_cache import get_schedule_index
from app.routing.stop_directory import build_stop_directory
from app.routing.traffic import get_traffic_estimator
from app.core.config import get_settings

router = APIRouter(prefix="/route-search", tags=["route-search"])
_routing_slots = asyncio.Semaphore(max(1, get_settings().routing_max_concurrency))


async def _routing_slot():
    """Bound memory-heavy searches on small shared-CPU deployments."""
    async with _routing_slots:
        yield


@router.post("", response_model=RouteSearchResponse)
async def route_search(
    request: RouteSearchRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    _slot: Annotated[None, Depends(_routing_slot)],
) -> RouteSearchResponse:
    try:
        graph = await get_routing_graph(session)
        schedule_index = await get_schedule_index(session)
        origin_stop_id, origin_access = await _resolve_endpoint(
            session,
            request,
            graph=graph,
            purpose=NearbyStopPurpose.ORIGIN,
        )
        destination_stop_id, destination_access = await _resolve_endpoint(
            session,
            request,
            graph=graph,
            purpose=NearbyStopPurpose.DESTINATION,
        )
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
            schedule_index=schedule_index,
        )
    except RouteNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error

    pedestrian_router = get_pedestrian_router()
    traffic_estimator = get_traffic_estimator()
    for option in options:
        option.segments = _collapse_contiguous_rides(option.segments)
        option.segments = await pedestrian_router.enrich_segments(option.segments)
        option.segments = await traffic_estimator.enrich_segments(
            option.segments, request.departure_at
        )
        option.total_duration_min = sum(
            segment.avg_duration_min + segment.scheduled_wait_min for segment in option.segments
        )
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


def _collapse_contiguous_rides(segments: list[Segment]) -> list[Segment]:
    """Expose one leg per vehicle while retaining the full map geometry."""
    collapsed: list[Segment] = []
    for segment in segments:
        if (
            collapsed
            and segment.mode is not TransportMode.WALK
            and collapsed[-1].mode is not TransportMode.WALK
            and collapsed[-1].route_id == segment.route_id
            and collapsed[-1].to_stop_id == segment.from_stop_id
        ):
            previous = collapsed[-1]
            coordinates = [*previous.coordinates]
            coordinates.extend(
                segment.coordinates[1:]
                if coordinates[-1] == segment.coordinates[0]
                else segment.coordinates
            )
            collapsed[-1] = previous.model_copy(
                update={
                    "to_stop_id": segment.to_stop_id,
                    "to_stop_name": segment.to_stop_name,
                    "to_stop_lat": segment.to_stop_lat,
                    "to_stop_lng": segment.to_stop_lng,
                    "avg_duration_min": previous.avg_duration_min + segment.avg_duration_min,
                    "coordinates": coordinates,
                }
            )
        else:
            collapsed.append(segment)
    return collapsed


async def _resolve_endpoint(
    session: AsyncSession,
    request: RouteSearchRequest,
    *,
    graph,
    purpose: NearbyStopPurpose,
) -> tuple[str, list[Segment]]:
    is_origin = purpose is NearbyStopPurpose.ORIGIN
    stop_id = request.origin_stop_id if is_origin else request.destination_stop_id
    if stop_id is not None:
        return stop_id, []

    lat = request.origin_lat if is_origin else request.destination_lat
    lng = request.origin_lng if is_origin else request.destination_lng
    assert lat is not None and lng is not None  # validated by RouteSearchRequest
    fixed_candidates = await find_nearby_stops(
        session,
        lat=lat,
        lng=lng,
        radius_meters=request.access_radius_meters,
        # Dense Mikrotrans corridors can otherwise crowd nearby rail stations
        # out of the candidate set. The pathfinder chooses globally among all
        # candidates instead of blindly snapping to the closest stop.
        limit=64,
        mode=None,
        purpose=purpose,
    )
    flexible_candidates = nearby_flexible_nodes(
        graph,
        lat=lat,
        lng=lng,
        radius_meters=request.access_radius_meters,
        can_board=is_origin,
    )
    candidates = sorted(
        [*fixed_candidates, *flexible_candidates],
        key=lambda candidate: candidate.distance_meters,
    )[:80]
    use_ride_hail = False
    if not candidates and request.allow_ride_hail:
        fixed_candidates = await find_nearby_stops(
            session,
            lat=lat,
            lng=lng,
            radius_meters=request.ride_hail_radius_meters,
            limit=96,
            mode=None,
            purpose=purpose,
        )
        flexible_candidates = nearby_flexible_nodes(
            graph,
            lat=lat,
            lng=lng,
            radius_meters=request.ride_hail_radius_meters,
            can_board=is_origin,
        )
        candidates = sorted(
            [*fixed_candidates, *flexible_candidates],
            key=lambda candidate: candidate.distance_meters,
        )[:80]
        use_ride_hail = bool(candidates)
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
            use_ride_hail=use_ride_hail,
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
    use_ride_hail: bool = False,
) -> Segment:
    from_stop_id, to_stop_id = (virtual_id, stop.id) if is_origin else (stop.id, virtual_id)
    coordinates = (
        [(pin_lng, pin_lat), (stop.lng, stop.lat)]
        if is_origin
        else [(stop.lng, stop.lat), (pin_lng, pin_lat)]
    )
    direction = "to transit" if is_origin else "to destination"
    mode = TransportMode.RIDE_HAIL if use_ride_hail else TransportMode.WALK
    route_code = "OJEK" if use_ride_hail else "WALK"
    route_name = f"Ojek online {direction} (estimasi)" if use_ride_hail else f"Walk {direction}"
    duration = (
        max(3.0, stop.distance_meters / (25_000 / 60))
        if use_ride_hail
        else max(0.5, stop.distance_meters / 75)
    )
    return Segment(
        id=f"access:{'origin' if is_origin else 'destination'}:{stop.id}",
        route_id=f"access:{'origin' if is_origin else 'destination'}",
        route_code=route_code,
        route_name=route_name,
        from_stop_id=from_stop_id,
        to_stop_id=to_stop_id,
        mode=mode,
        service_category=ServiceCategory.TRANSFER,
        service_name=route_name,
        avg_duration_min=round(duration, 1),
        fare=15000 if use_ride_hail else 0,
        fare_product_id="ride-hail:estimate" if use_ride_hail else "free:walk",
        data_confidence=DataConfidence.COMMUNITY,
        last_verified_at=date.today(),
        color="64748B",
        coordinates=coordinates,
        from_stop_name="Titik di peta" if is_origin else stop.name,
        to_stop_name=stop.name if is_origin else "Titik di peta",
        from_stop_lat=pin_lat if is_origin else stop.lat,
        from_stop_lng=pin_lng if is_origin else stop.lng,
        to_stop_lat=stop.lat if is_origin else pin_lat,
        to_stop_lng=stop.lng if is_origin else pin_lng,
    )
