import asyncio
from datetime import date
from math import asin, cos, radians, sin, sqrt
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import get_session
from app.db.transit_repository import find_nearby_stops
from app.fares.catalog import DEFAULT_FARE_CATALOG
from app.fares.engine import quote_journey
from app.geocoding.service import get_geocoding_service
from app.models.schema import (
    DataConfidence,
    NearbyStop,
    NearbyStopPurpose,
    RouteOption,
    RouteSearchRequest,
    RouteSearchResponse,
    SearchCriteria,
    Segment,
    ServiceCategory,
    TransportMode,
)
from app.routing.flexible import nearby_flexible_nodes
from app.routing.geojson_builder import build_feature_collection
from app.routing.graph_cache import get_routing_graph
from app.routing.pathfinder import RouteNotFoundError, find_route_options
from app.routing.pedestrian import PedestrianMeasure, get_pedestrian_router
from app.routing.schedule_cache import get_schedule_index
from app.routing.stop_directory import build_stop_directory
from app.routing.traffic import get_traffic_estimator
from app.routing.transfers import nearby_endpoint_access_nodes
from app.routing.weather import get_weather_estimator

router = APIRouter(prefix="/route-search", tags=["route-search"])
_routing_slots = asyncio.Semaphore(max(1, get_settings().routing_max_concurrency))
WALKING_DETOUR_FACTOR = 1.25
UI_STATION_COORDINATE = (-6.3605313, 106.8317755)
UI_TRACK_BARRIER_LNG = 106.83190


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

    direct_ride_hail = _direct_ride_hail_option(request, options)
    if direct_ride_hail is not None:
        options.append(direct_ride_hail)

    pedestrian_router = get_pedestrian_router()
    traffic_estimator = get_traffic_estimator()
    weather_estimator = get_weather_estimator()
    await _enrich_flexible_landmarks(options)
    for option in options:
        option.segments = _collapse_contiguous_rides(option.segments)
        option.segments = await pedestrian_router.enrich_segments(option.segments)
        option.segments = await weather_estimator.enrich_segments(
            option.segments, request.departure_at
        )
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
    for option in options:
        option.segments = _remove_zero_length_walks(option.segments)
        option.segments = _apply_segment_distances(_label_flexible_points(option.segments))
        option.total_distance_meters = round(
            sum(segment.distance_meters or 0 for segment in option.segments)
        )
        option.fare_quote = quote_journey(
            option.segments,
            catalog=DEFAULT_FARE_CATALOG,
            departure_at=request.departure_at,
            payment_profile=request.payment_profile,
        )
        option.total_fare = option.fare_quote.estimated_amount
        option.geojson = build_feature_collection(option.segments)
    options = [
        option
        for option in options
        if not (
            option.segments
            and option.segments[0].route_id == "ride-hail:direct"
            and option.total_distance_meters > request.ride_hail_radius_meters
        )
    ]
    options = _rank_final_options(options)
    return RouteSearchResponse(
        origin_stop_id=origin_stop_id,
        destination_stop_id=destination_stop_id,
        options=options,
    )


def _direct_ride_hail_option(
    request: RouteSearchRequest, transit_options: list[RouteOption]
) -> RouteOption | None:
    """Offer a direct road fallback only when transit already needs an ojek connector."""
    if (
        not request.allow_ride_hail
        or request.origin_lat is None
        or request.origin_lng is None
        or request.destination_lat is None
        or request.destination_lng is None
        or not any(
            segment.mode is TransportMode.RIDE_HAIL
            for option in transit_options
            for segment in option.segments
        )
    ):
        return None
    coordinates = [
        (request.origin_lng, request.origin_lat),
        (request.destination_lng, request.destination_lat),
    ]
    estimated_distance = _geometry_distance_meters(coordinates) * WALKING_DETOUR_FACTOR
    if estimated_distance > request.ride_hail_radius_meters:
        return None
    segment = Segment(
        id="ride-hail:direct",
        route_id="ride-hail:direct",
        route_code="OJEK",
        route_name="Ojek online langsung (estimasi)",
        from_stop_id="coordinate:origin",
        to_stop_id="coordinate:destination",
        mode=TransportMode.RIDE_HAIL,
        service_category=ServiceCategory.TRANSFER,
        service_name="Ojek online langsung (estimasi)",
        avg_duration_min=max(3, estimated_distance / (25_000 / 60)),
        fare=15000,
        fare_product_id="ride-hail:estimate",
        data_confidence=DataConfidence.COMMUNITY,
        last_verified_at=date.today(),
        color="64748B",
        coordinates=coordinates,
        from_stop_name=request.origin_label or "Lokasi awal",
        to_stop_name=request.destination_label or "Tujuan",
        from_stop_lat=request.origin_lat,
        from_stop_lng=request.origin_lng,
        to_stop_lat=request.destination_lat,
        to_stop_lng=request.destination_lng,
        distance_meters=estimated_distance,
    )
    fare_quote = quote_journey(
        [segment],
        catalog=DEFAULT_FARE_CATALOG,
        departure_at=request.departure_at,
        payment_profile=request.payment_profile,
    )
    return RouteOption(
        criteria=SearchCriteria.FASTEST,
        total_duration_min=segment.avg_duration_min,
        total_fare=fare_quote.estimated_amount,
        total_distance_meters=estimated_distance,
        fare_quote=fare_quote,
        transfer_count=0,
        segments=[segment],
        geojson=build_feature_collection([segment]),
    )


def _rank_final_options(options: list[RouteOption]) -> list[RouteOption]:
    if not options:
        return []
    fastest = min(options, key=lambda option: (option.total_duration_min, option.total_fare))
    cheapest = min(options, key=lambda option: (option.total_fare, option.total_duration_min))
    return [
        fastest.model_copy(update={"criteria": SearchCriteria.FASTEST}),
        cheapest.model_copy(update={"criteria": SearchCriteria.CHEAPEST}),
    ]


def _remove_zero_length_walks(segments: list[Segment]) -> list[Segment]:
    return [
        segment
        for segment in segments
        if not (
            segment.mode is TransportMode.WALK
            and (segment.walking_distance_meters or 0) < 5
            and segment.from_stop_name.strip().casefold() == segment.to_stop_name.strip().casefold()
        )
    ]


def _collapse_contiguous_rides(segments: list[Segment]) -> list[Segment]:
    """Expose one leg per vehicle or continuous walk with complete geometry."""
    collapsed: list[Segment] = []
    for segment in segments:
        joins_previous = bool(collapsed and collapsed[-1].to_stop_id == segment.from_stop_id)
        same_walk = bool(
            joins_previous
            and segment.mode is TransportMode.WALK
            and collapsed[-1].mode is TransportMode.WALK
            and collapsed[-1].route_id == segment.route_id
            and collapsed[-1].access_action is None
            and segment.access_action is None
        )
        same_vehicle = bool(
            joins_previous
            and segment.mode is not TransportMode.WALK
            and collapsed[-1].mode is not TransportMode.WALK
            and collapsed[-1].route_id == segment.route_id
        )
        if same_walk or same_vehicle:
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


def _label_flexible_points(segments: list[Segment]) -> list[Segment]:
    """Name hail-and-ride points after an adjacent real stop or user place."""
    names: dict[str, str] = {}
    for segment in segments:
        if _is_specific_place(segment.from_stop_name):
            names[segment.from_stop_id] = segment.from_stop_name
        if _is_specific_place(segment.to_stop_name):
            names[segment.to_stop_id] = segment.to_stop_name

    for segment in segments:
        if segment.mode is not TransportMode.WALK:
            continue
        from_name = names.get(segment.from_stop_id)
        to_name = names.get(segment.to_stop_id)
        if (
            segment.from_stop_id.startswith("flex:")
            and segment.from_stop_id not in names
            and to_name
        ):
            names[segment.from_stop_id] = f"Dekat {to_name}"
        if segment.to_stop_id.startswith("flex:") and segment.to_stop_id not in names and from_name:
            names[segment.to_stop_id] = f"Dekat {from_name}"

    for index, segment in enumerate(segments):
        if (
            segment.mode is not TransportMode.WALK
            or not segment.from_stop_id.startswith("flex:")
            or not segment.to_stop_id.startswith("flex:")
        ):
            continue
        previous = segments[index - 1] if index > 0 else None
        following = segments[index + 1] if index + 1 < len(segments) else None
        if previous is None or following is None:
            continue
        transfer_name = f"Titik pindah {previous.route_code} / {following.route_code}"
        names.setdefault(segment.from_stop_id, transfer_name)
        names.setdefault(segment.to_stop_id, transfer_name)

    return [
        segment.model_copy(
            update={
                "from_stop_name": names.get(segment.from_stop_id, segment.from_stop_name),
                "to_stop_name": names.get(segment.to_stop_id, segment.to_stop_name),
            }
        )
        for segment in segments
    ]


async def _enrich_flexible_landmarks(options: list[RouteOption]) -> None:
    points: dict[str, tuple[float, float]] = {}
    for option in options:
        for segment in option.segments:
            if segment.mode is TransportMode.WALK:
                continue
            if segment.from_stop_id.startswith("flex:") and segment.from_stop_lat is not None:
                points[segment.from_stop_id] = (
                    segment.from_stop_lat,
                    segment.from_stop_lng or 0,
                )
            if segment.to_stop_id.startswith("flex:") and segment.to_stop_lat is not None:
                points[segment.to_stop_id] = (segment.to_stop_lat, segment.to_stop_lng or 0)
    selected = list(points.items())[:8]
    geocoder = get_geocoding_service()
    results = await asyncio.gather(
        *(geocoder.describe_nearby(lat, lng) for _, (lat, lng) in selected),
        return_exceptions=True,
    )
    names = {
        node_id: f"Dekat {result.label}"
        for (node_id, _), result in zip(selected, results, strict=True)
        if not isinstance(result, Exception) and result.label.casefold() != "lokasi"
    }
    if not names:
        return
    for option in options:
        option.segments = [
            segment.model_copy(
                update={
                    "from_stop_name": names.get(segment.from_stop_id, segment.from_stop_name),
                    "to_stop_name": names.get(segment.to_stop_id, segment.to_stop_name),
                }
            )
            for segment in option.segments
        ]


def _is_specific_place(name: str) -> bool:
    cleaned = name.strip().casefold()
    return (
        bool(cleaned)
        and cleaned not in {"titik di peta", "lokasi awal", "tujuan"}
        and not (cleaned.startswith("koridor "))
    )


def _apply_segment_distances(segments: list[Segment]) -> list[Segment]:
    result: list[Segment] = []
    for segment in segments:
        distance = segment.distance_meters
        if distance is None:
            distance = (
                segment.walking_distance_meters
                if segment.mode is TransportMode.WALK
                and segment.walking_distance_meters is not None
                else _geometry_distance_meters(segment.coordinates)
            )
        result.append(segment.model_copy(update={"distance_meters": round(distance)}))
    return result


def _geometry_distance_meters(coordinates: list[tuple[float, float]]) -> float:
    distance = 0.0
    for first, second in zip(coordinates, coordinates[1:], strict=False):
        lng1, lat1 = first
        lng2, lat2 = second
        delta_lat = radians(lat2 - lat1)
        delta_lng = radians(lng2 - lng1)
        value = sin(delta_lat / 2) ** 2 + (
            cos(radians(lat1)) * cos(radians(lat2)) * sin(delta_lng / 2) ** 2
        )
        distance += 2 * 6_371_008.8 * asin(sqrt(value))
    return distance


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
    pin_label = request.origin_label if is_origin else request.destination_label
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
    access_candidates = nearby_endpoint_access_nodes(
        graph,
        lat=lat,
        lng=lng,
        radius_meters=request.access_radius_meters,
    )
    candidates = sorted(
        [*fixed_candidates, *flexible_candidates, *access_candidates],
        key=lambda candidate: candidate.distance_meters,
    )
    if _is_east_of_ui_station(lat, lng):
        # The rail line is a real pedestrian barrier. Entering through a stop
        # centroid would bypass the modeled gate/tap path.
        candidates = [
            candidate
            for candidate in candidates
            if candidate.lng > UI_TRACK_BARRIER_LNG
        ]
    candidates = _shortlist_access_candidates(candidates)
    measures = await get_pedestrian_router().measure_distances(
        (lng, lat), [(candidate.lng, candidate.lat) for candidate in candidates]
    )
    measured_candidates: list[NearbyStop] = []
    measures_by_stop: dict[str, PedestrianMeasure] = {}
    for candidate, measure in zip(candidates, measures, strict=True):
        if measure.distance_meters > request.access_radius_meters:
            continue
        measured_candidates.append(
            candidate.model_copy(update={"distance_meters": measure.distance_meters})
        )
        measures_by_stop[candidate.id] = measure
    candidates = measured_candidates
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
        )[:48]
        ride_hail_measures = await get_pedestrian_router().measure_distances(
            (lng, lat),
            [(candidate.lng, candidate.lat) for candidate in candidates],
            TransportMode.RIDE_HAIL,
        )
        road_candidates: list[NearbyStop] = []
        for candidate, measure in zip(candidates, ride_hail_measures, strict=True):
            if measure.distance_meters > request.ride_hail_radius_meters:
                continue
            road_candidates.append(
                candidate.model_copy(update={"distance_meters": measure.distance_meters})
            )
            measures_by_stop[candidate.id] = measure
        candidates = road_candidates
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
            pin_label=pin_label,
            pedestrian_measure=measures_by_stop.get(stop.id),
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
    pin_label: str | None = None,
    pedestrian_measure: PedestrianMeasure | None = None,
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
        max(
            3.0,
            pedestrian_measure.duration_min
            if pedestrian_measure is not None
            else stop.distance_meters / (25_000 / 60),
        )
        if use_ride_hail
        else max(
            0.5,
            pedestrian_measure.duration_min
            if pedestrian_measure is not None
            else stop.distance_meters * WALKING_DETOUR_FACTOR / 75,
        )
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
        from_stop_name=(pin_label or "Lokasi awal") if is_origin else stop.name,
        to_stop_name=stop.name if is_origin else (pin_label or "Tujuan"),
        from_stop_lat=pin_lat if is_origin else stop.lat,
        from_stop_lng=pin_lng if is_origin else stop.lng,
        to_stop_lat=stop.lat if is_origin else pin_lat,
        to_stop_lng=stop.lng if is_origin else pin_lng,
        walking_distance_meters=(
            None
            if use_ride_hail
            else pedestrian_measure.distance_meters
            if pedestrian_measure is not None
            else stop.distance_meters * WALKING_DETOUR_FACTOR
        ),
        distance_meters=(
            pedestrian_measure.distance_meters
            if use_ride_hail and pedestrian_measure is not None
            else None
        ),
    )


def _shortlist_access_candidates(candidates: list[NearbyStop]) -> list[NearbyStop]:
    """Keep mode diversity before one pedestrian matrix request."""
    fixed_by_mode: dict[TransportMode, list[NearbyStop]] = {}
    flexible: list[NearbyStop] = []
    for candidate in candidates:
        if candidate.id.startswith("flex:"):
            flexible.append(candidate)
            continue
        bucket = fixed_by_mode.setdefault(candidate.modes[0], [])
        if len(bucket) < 4:
            bucket.append(candidate)
    selected = [candidate for bucket in fixed_by_mode.values() for candidate in bucket]
    selected.extend(flexible[:24])
    return sorted(selected, key=lambda candidate: candidate.distance_meters)[:48]


def _is_east_of_ui_station(lat: float, lng: float) -> bool:
    return (
        lng > 106.83195
        and _geometry_distance_meters(
            [(UI_STATION_COORDINATE[1], UI_STATION_COORDINATE[0]), (lng, lat)]
        )
        <= 1500
    )
