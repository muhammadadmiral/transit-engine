"""Cached aggregation of free OpenStreetMap geocoders."""

import asyncio
import re
from collections import OrderedDict
from time import monotonic
from typing import Any
from urllib.parse import quote

import httpx

from app.core.config import Settings, get_settings
from app.models.schema import GeocodeSource, PlaceResult

JABODETABEK_NOMINATIM_VIEWBOX = "106.30,-5.80,107.40,-6.95"
JABODETABEK_PHOTON_BBOX = "106.30,-6.95,107.40,-5.80"
CACHE_TTL_SECONDS = 24 * 60 * 60
CACHE_MAX_ENTRIES = 512


class GeocoderUnavailableError(RuntimeError):
    pass


class PlaceNotFoundError(ValueError):
    pass


class GeocodingService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._cache: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._nominatim_lock = asyncio.Lock()
        self._last_nominatim_request_at = 0.0

    async def search(self, query: str, limit: int = 6) -> list[PlaceResult]:
        cache_key = f"search:{query.casefold().strip()}:{limit}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        upstream: list[PlaceResult] = []
        errors: list[Exception] = []
        candidate_limit = max(6, limit)
        provider_count = 2 + int(bool(self.settings.effective_tomtom_api_key))
        if self.settings.effective_tomtom_api_key:
            try:
                upstream.extend(await self._search_tomtom(query, candidate_limit))
            except (httpx.HTTPError, ValueError, TypeError) as error:
                errors.append(error)

        # Keep the free providers as fallbacks and gap-fillers. A configured
        # TomTom result is ranked first, but no landmark name is special-cased.
        if len(upstream) < candidate_limit:
            try:
                upstream.extend(await self._search_nominatim(query, candidate_limit))
            except (httpx.HTTPError, ValueError, TypeError) as error:
                errors.append(error)

        if not self.settings.effective_tomtom_api_key or len(upstream) < candidate_limit:
            try:
                upstream.extend(await self._search_photon(query, candidate_limit))
            except (httpx.HTTPError, ValueError, TypeError) as error:
                errors.append(error)

        results = _rank_results(query, _deduplicate(upstream, len(upstream)))[:limit]
        if not results and len(errors) == provider_count:
            raise GeocoderUnavailableError from errors[-1]
        self._put_cached(cache_key, results)
        return results

    async def reverse(self, lat: float, lng: float) -> PlaceResult:
        cache_key = f"reverse:{lat:.5f}:{lng:.5f}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        requests = [self._reverse_nominatim(lat, lng), self._reverse_photon(lat, lng)]
        if self.settings.effective_tomtom_api_key:
            requests.insert(0, self._reverse_tomtom(lat, lng))
        responses = await asyncio.gather(*requests, return_exceptions=True)
        candidates = [response for response in responses if isinstance(response, PlaceResult)]
        if not candidates and all(isinstance(response, Exception) for response in responses):
            raise GeocoderUnavailableError from responses[-1]
        if not candidates:
            raise PlaceNotFoundError
        result = max(candidates, key=_reverse_score)
        self._put_cached(cache_key, result)
        return result

    async def _search_nominatim(self, query: str, limit: int) -> list[PlaceResult]:
        payload = await self._nominatim_request(
            "/search",
            {
                "q": query,
                "format": "jsonv2",
                "addressdetails": "1",
                "limit": str(limit),
                "countrycodes": "id",
                "viewbox": JABODETABEK_NOMINATIM_VIEWBOX,
                "bounded": "1",
                "accept-language": "id",
            },
        )
        if not isinstance(payload, list):
            raise ValueError("Unexpected Nominatim search response")
        return [_from_nominatim(row) for row in payload if isinstance(row, dict)]

    async def _reverse_nominatim(self, lat: float, lng: float) -> PlaceResult | None:
        payload = await self._nominatim_request(
            "/reverse",
            {
                "lat": str(lat),
                "lon": str(lng),
                "zoom": "18",
                "format": "jsonv2",
                "addressdetails": "1",
                "accept-language": "id",
            },
        )
        if not isinstance(payload, dict) or not payload.get("display_name"):
            return None
        return _from_nominatim(payload)

    async def _nominatim_request(self, path: str, params: dict[str, str]) -> Any:
        async with self._nominatim_lock:
            elapsed = monotonic() - self._last_nominatim_request_at
            if elapsed < self.settings.geocoder_nominatim_interval_seconds:
                await asyncio.sleep(self.settings.geocoder_nominatim_interval_seconds - elapsed)
            async with httpx.AsyncClient(timeout=self.settings.geocoder_timeout_seconds) as client:
                response = await client.get(
                    f"{self.settings.geocoder_nominatim_url.rstrip('/')}{path}",
                    params=params,
                    headers={
                        "Accept": "application/json",
                        "User-Agent": self.settings.geocoder_user_agent,
                    },
                )
                self._last_nominatim_request_at = monotonic()
                response.raise_for_status()
                return response.json()

    async def _search_photon(self, query: str, limit: int) -> list[PlaceResult]:
        payload = await self._photon_request(
            "/api/", {"q": query, "limit": str(limit), "bbox": JABODETABEK_PHOTON_BBOX}
        )
        features = payload.get("features", []) if isinstance(payload, dict) else []
        return [_from_photon(row) for row in features if isinstance(row, dict)]

    async def _reverse_photon(self, lat: float, lng: float) -> PlaceResult | None:
        payload = await self._photon_request(
            "/reverse", {"lat": str(lat), "lon": str(lng), "limit": "1"}
        )
        features = payload.get("features", []) if isinstance(payload, dict) else []
        return _from_photon(features[0]) if features else None

    async def _photon_request(self, path: str, params: dict[str, str]) -> Any:
        async with httpx.AsyncClient(timeout=self.settings.geocoder_timeout_seconds) as client:
            response = await client.get(
                f"{self.settings.geocoder_photon_url.rstrip('/')}{path}",
                params=params,
                headers={
                    "Accept": "application/json",
                    "User-Agent": self.settings.geocoder_user_agent,
                },
            )
            response.raise_for_status()
            return response.json()

    async def _search_tomtom(self, query: str, limit: int) -> list[PlaceResult]:
        payload = await self._tomtom_request(
            f"/search/{quote(query.strip(), safe='')}.json",
            {
                "countrySet": "ID",
                "lat": "-6.2700",
                "limit": str(limit),
                "lon": "106.8300",
                "language": "id-ID",
                "typeahead": "false",
            },
        )
        rows = payload.get("results", []) if isinstance(payload, dict) else []
        return [_from_tomtom(row) for row in rows if isinstance(row, dict)]

    async def _reverse_tomtom(self, lat: float, lng: float) -> PlaceResult | None:
        payload = await self._tomtom_request(
            f"/reverseGeocode/{lat},{lng}.json",
            {"language": "id-ID", "radius": "120"},
        )
        rows = payload.get("addresses", []) if isinstance(payload, dict) else []
        return _from_tomtom(rows[0], reverse=True) if rows else None

    async def _tomtom_request(self, path: str, params: dict[str, str]) -> Any:
        params = {**params, "key": self.settings.effective_tomtom_api_key}
        async with httpx.AsyncClient(timeout=self.settings.geocoder_timeout_seconds) as client:
            response = await client.get(
                f"{self.settings.tomtom_search_url.rstrip('/')}{path}",
                params=params,
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()
            return response.json()

    def _get_cached(self, key: str) -> Any | None:
        cached = self._cache.get(key)
        if cached is None:
            return None
        created_at, value = cached
        if monotonic() - created_at >= CACHE_TTL_SECONDS:
            self._cache.pop(key, None)
            return None
        self._cache.move_to_end(key)
        return value

    def _put_cached(self, key: str, value: Any) -> None:
        self._cache[key] = (monotonic(), value)
        self._cache.move_to_end(key)
        while len(self._cache) > CACHE_MAX_ENTRIES:
            self._cache.popitem(last=False)


def _from_nominatim(row: dict[str, Any]) -> PlaceResult:
    address = row.get("address") if isinstance(row.get("address"), dict) else {}
    display_name = str(row.get("display_name") or "")
    label = str(row.get("name") or display_name.split(",", maxsplit=1)[0] or "Lokasi")
    return PlaceResult(
        area=_area(address),
        category=str(row.get("type") or row.get("category") or "place"),
        id=f"nominatim:{row.get('osm_type', 'place')}:{row.get('osm_id', row.get('place_id', ''))}",
        label=label,
        lat=float(row["lat"]),
        lng=float(row["lon"]),
        subtitle=display_name,
        source=GeocodeSource.NOMINATIM,
    )


def _from_photon(feature: dict[str, Any]) -> PlaceResult:
    properties = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    coordinates = feature.get("geometry", {}).get("coordinates", [])
    if len(coordinates) < 2:
        raise ValueError("Photon feature has no point geometry")
    subtitle_parts = [
        properties.get(key)
        for key in ("street", "district", "city", "state", "country")
        if properties.get(key)
    ]
    return PlaceResult(
        area=str(
            properties.get("city")
            or properties.get("district")
            or properties.get("state")
            or "Indonesia"
        ),
        category=str(properties.get("osm_value") or properties.get("type") or "place"),
        id=f"photon:{properties.get('osm_type', 'place')}:{properties.get('osm_id', '')}",
        label=str(properties.get("name") or properties.get("street") or "Lokasi"),
        lat=float(coordinates[1]),
        lng=float(coordinates[0]),
        subtitle=", ".join(map(str, subtitle_parts)),
        source=GeocodeSource.PHOTON,
    )


def _from_tomtom(row: dict[str, Any], *, reverse: bool = False) -> PlaceResult:
    address = row.get("address") if isinstance(row.get("address"), dict) else {}
    position = row.get("position") if isinstance(row.get("position"), dict) else {}
    poi = row.get("poi") if isinstance(row.get("poi"), dict) else {}
    classifications = (
        poi.get("classifications") if isinstance(poi.get("classifications"), list) else []
    )
    classification = (
        classifications[0]
        if classifications and isinstance(classifications[0], dict)
        else {}
    )
    names = classification.get("names") if isinstance(classification.get("names"), list) else []
    category = str(
        classification.get("code")
        or (names[0].get("name") if names and isinstance(names[0], dict) else "")
        or row.get("type")
        or "address"
    )
    label = str(
        poi.get("name")
        or address.get("freeformAddress")
        or address.get("streetName")
        or "Lokasi"
    )
    subtitle = str(address.get("freeformAddress") or label)
    result_type = "reverse" if reverse else str(row.get("type") or "place")
    provider_id = str(row.get("id") or f"{position.get('lat', '')},{position.get('lon', '')}")
    return PlaceResult(
        area=str(
            address.get("municipality")
            or address.get("municipalitySubdivision")
            or address.get("countrySubdivision")
            or "Indonesia"
        ),
        category=category,
        id=f"tomtom:{result_type}:{provider_id}",
        label=label,
        lat=float(position["lat"]),
        lng=float(position["lon"]),
        subtitle=subtitle,
        source=GeocodeSource.TOMTOM,
    )


def _area(address: dict[str, Any]) -> str:
    return str(
        address.get("city")
        or address.get("town")
        or address.get("municipality")
        or address.get("county")
        or address.get("state")
        or "Indonesia"
    )


def _deduplicate(results: list[PlaceResult], limit: int) -> list[PlaceResult]:
    unique: list[PlaceResult] = []
    for result in results:
        duplicate = next(
            (
                existing
                for existing in unique
                if abs(existing.lat - result.lat) < 0.00015
                and abs(existing.lng - result.lng) < 0.00015
            ),
            None,
        )
        if duplicate is None:
            unique.append(result)
        if len(unique) == limit:
            break
    return unique


def _rank_results(query: str, results: list[PlaceResult]) -> list[PlaceResult]:
    """Rerank provider results generically; never special-case a landmark name."""
    query_tokens = _tokens(query)

    def score(result: PlaceResult) -> tuple[float, int, int]:
        label_tokens = _tokens(result.label)
        all_tokens = label_tokens | _tokens(result.subtitle) | _tokens(result.area)
        matched_weight = sum(
            (2.0 if len(token) == 1 else 1.0) for token in query_tokens & all_tokens
        )
        total_weight = sum((2.0 if len(token) == 1 else 1.0) for token in query_tokens) or 1
        coverage = matched_weight / total_weight
        normalized_query = " ".join(query.casefold().split())
        normalized_label = " ".join(result.label.casefold().split())
        phrase_bonus = (
            2 if normalized_label == normalized_query else int(normalized_label in normalized_query)
        )
        provider_priority = 2 if result.source is GeocodeSource.TOMTOM else 1
        return coverage, phrase_bonus, provider_priority

    return sorted(results, key=score, reverse=True)


def _tokens(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", value.casefold()))


def _reverse_score(result: PlaceResult) -> tuple[int, int]:
    """Prefer named POIs/addresses over a nearby road without knowing POI names."""
    category = result.category.casefold()
    if category in {
        "university",
        "school",
        "hospital",
        "station",
        "mall",
        "marketplace",
        "place_of_worship",
        "office",
    }:
        specificity = 3
    elif category in {"house", "building", "address", "residential"}:
        specificity = 2
    else:
        specificity = 1
    return specificity, len(result.subtitle)


_service: GeocodingService | None = None


def get_geocoding_service() -> GeocodingService:
    global _service
    if _service is None:
        _service = GeocodingService()
    return _service
