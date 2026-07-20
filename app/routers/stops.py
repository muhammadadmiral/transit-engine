"""Stop lookup endpoint used by origin and destination autocomplete."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.db.transit_repository import find_nearby_stops, search_stops
from app.models.schema import NearbyStop, NearbyStopPurpose, Stop, TransportMode

router = APIRouter(prefix="/stops", tags=["stops"])


@router.get("/nearby", response_model=list[NearbyStop])
async def nearby_stops(
    session: Annotated[AsyncSession, Depends(get_session)],
    lat: Annotated[float, Query(ge=-90, le=90)],
    lng: Annotated[float, Query(ge=-180, le=180)],
    radius_meters: Annotated[int, Query(alias="radiusMeters", ge=50, le=5000)] = 1000,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
    mode: TransportMode | None = None,
    purpose: NearbyStopPurpose = NearbyStopPurpose.ANY,
) -> list[NearbyStop]:
    try:
        return await find_nearby_stops(
            session,
            lat=lat,
            lng=lng,
            radius_meters=radius_meters,
            limit=limit,
            mode=mode,
            purpose=purpose,
        )
    except (OSError, SQLAlchemyError) as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Nearby transit stops are temporarily unavailable",
        ) from error


@router.get("", response_model=list[Stop])
async def list_stops(
    q: Annotated[str, Query(min_length=2, max_length=80)],
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> list[Stop]:
    try:
        return await search_stops(session, q, limit)
    except (OSError, SQLAlchemyError) as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Transit stops are temporarily unavailable",
        ) from error
