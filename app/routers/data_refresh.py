"""Authenticated data refresh endpoints for official source feeds."""

from secrets import compare_digest
from urllib.error import URLError

from fastapi import APIRouter, Header, HTTPException, status
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings
from app.ingestion.gtfs.import_transjakarta import import_url
from app.models.schema import DataRefreshResponse

router = APIRouter(prefix="/data-refresh", tags=["data-refresh"])


@router.post("/transjakarta", response_model=DataRefreshResponse)
async def refresh_transjakarta(
    x_data_refresh_secret: str | None = Header(default=None),
) -> DataRefreshResponse:
    settings = get_settings()
    if not settings.data_refresh_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Data refresh is not configured",
        )
    if x_data_refresh_secret is None or not compare_digest(
        x_data_refresh_secret, settings.data_refresh_secret
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh secret"
        )

    try:
        stops_imported, segments_imported = await import_url(settings.transjakarta_gtfs_url)
    except (OSError, URLError, SQLAlchemyError) as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="TransJakarta data refresh failed",
        ) from error

    return DataRefreshResponse(
        source="transjakarta",
        stops_imported=stops_imported,
        segments_imported=segments_imported,
    )
