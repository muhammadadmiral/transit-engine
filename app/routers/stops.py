"""Stop lookup endpoint used by origin and destination autocomplete."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.db.transit_repository import search_stops
from app.models.schema import Stop

router = APIRouter(prefix="/stops", tags=["stops"])


@router.get("", response_model=list[Stop])
async def list_stops(
    q: Annotated[str, Query(min_length=2, max_length=80)],
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> list[Stop]:
    try:
        return await search_stops(session, q, limit)
    except SQLAlchemyError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Transit stops are temporarily unavailable",
        ) from error
