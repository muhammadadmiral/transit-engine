"""Fetch angkot route relations from the public Overpass API."""

import asyncio
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)
OVERPASS_URL = "https://lz4.overpass-api.de/api/interpreter"
REGIONS = {
    "Depok": "-6.44, 106.75, -6.34, 106.87",
    "Bogor": "-6.70, 106.60, -6.44, 107.00",
    "Tangerang": "-6.35, 106.40, -6.05, 106.75",
    "Bekasi": "-6.40, 106.90, -6.00, 107.30",
}


def build_query(bbox: str) -> str:
    pattern = "angkot|angkutan kota|mikrolet|kwk|koasi"
    return f"""
    [out:json][timeout:180];
    (
      relation["route"="share_taxi"]({bbox});
      relation["route"="minibus"]({bbox});
      relation["route"="bus"]["name"~"{pattern}",i]({bbox});
      relation["route"="bus"]["operator"~"{pattern}",i]({bbox});
      relation["route"="bus"]["network"~"{pattern}",i]({bbox});
    );
    out geom;
    """


async def fetch_angkot_relations() -> list[dict[str, Any]]:
    elements_by_id: dict[tuple[str, int], dict[str, Any]] = {}
    headers = {"User-Agent": "transit-engine/1.0"}
    async with httpx.AsyncClient(timeout=180.0) as client:
        for index, (region_name, bbox) in enumerate(REGIONS.items()):
            elements = await _fetch_region(client, region_name, build_query(bbox), headers)
            for element in elements:
                element_id = element.get("id")
                if isinstance(element_id, int):
                    elements_by_id[(str(element.get("type", "relation")), element_id)] = element
            if elements and index < len(REGIONS) - 1:
                await asyncio.sleep(10)
    return list(elements_by_id.values())


async def _fetch_region(
    client: httpx.AsyncClient,
    region_name: str,
    query: str,
    headers: dict[str, str],
) -> list[dict[str, Any]]:
    for attempt in range(3):
        logger.info("Fetching angkot routes for %s (attempt %s/3)", region_name, attempt + 1)
        try:
            response = await client.post(OVERPASS_URL, data={"data": query}, headers=headers)
            response.raise_for_status()
            elements = response.json().get("elements", [])
            logger.info("Found %s candidate routes in %s", len(elements), region_name)
            return elements
        except httpx.HTTPStatusError as error:
            retryable = error.response.status_code == 429 or error.response.status_code >= 500
            if not retryable or attempt == 2:
                logger.error("Overpass rejected %s: %s", region_name, error)
                return []
        except (httpx.HTTPError, ValueError) as error:
            if attempt == 2:
                logger.error("Failed to fetch %s: %s", region_name, error)
                return []
        await asyncio.sleep(15 * (attempt + 1))
    return []
