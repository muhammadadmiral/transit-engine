"""Place search and reverse geocoding served through the transit backend."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.geocoding.service import (
    GeocoderUnavailableError,
    GeocodingService,
    PlaceNotFoundError,
    get_geocoding_service,
)
from app.models.schema import PlaceResult

router = APIRouter(prefix="/geocode", tags=["geocode"])


@router.get("/search", response_model=list[PlaceResult])
async def search_places(
    q: Annotated[str, Query(min_length=3, max_length=100)],
    geocoder: Annotated[GeocodingService, Depends(get_geocoding_service)],
    limit: Annotated[int, Query(ge=1, le=10)] = 6,
) -> list[PlaceResult]:
    try:
        return await geocoder.search(q.strip(), limit)
    except GeocoderUnavailableError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Pencarian lokasi sementara tidak tersedia",
        ) from error


@router.get("/reverse", response_model=PlaceResult)
async def reverse_geocode(
    lat: Annotated[float, Query(ge=-90, le=90)],
    lng: Annotated[float, Query(ge=-180, le=180)],
    geocoder: Annotated[GeocodingService, Depends(get_geocoding_service)],
) -> PlaceResult:
    try:
        return await geocoder.reverse(lat, lng)
    except PlaceNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Alamat tidak ditemukan"
        ) from error
    except GeocoderUnavailableError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Reverse geocode sementara tidak tersedia",
        ) from error
