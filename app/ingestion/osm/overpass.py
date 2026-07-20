import json
from typing import Any
import httpx
import logging
import asyncio

logger = logging.getLogger(__name__)

# Bounding boxes for Jabodetabek regions
REGIONS = {
    # "Depok": "-6.44, 106.75, -6.34, 106.87",
    # "Bogor": "-6.70, 106.60, -6.44, 107.00",
    "Tangerang": "-6.35, 106.40, -6.05, 106.75",
    "Bekasi": "-6.40, 106.90, -6.00, 107.30",
}

def build_query(bbox: str) -> str:
    return f"""
    [out:json][timeout:180];
    (
      relation["route"="share_taxi"]({bbox});
      relation["route"="minibus"]({bbox});
      relation["route"="bus"]({bbox});
    );
    out geom;
    """

async def fetch_angkot_relations() -> list[dict[str, Any]]:
    headers = {"User-Agent": "transit-engine/1.0"}
    all_elements = []
    
    async with httpx.AsyncClient(timeout=180.0) as client:
        for region_name, bbox in REGIONS.items():
            query = build_query(bbox)
            
            max_retries = 3
            for attempt in range(max_retries):
                logger.info(f"Fetching Angkot routes for {region_name} (Attempt {attempt+1}/{max_retries})...")
                try:
                    response = await client.post(
                        "https://lz4.overpass-api.de/api/interpreter", 
                        data={"data": query}, 
                        headers=headers
                    )
                    response.raise_for_status()
                    result = response.json()
                    elements = result.get("elements", [])
                    logger.info(f"Found {len(elements)} routes in {region_name}.")
                    all_elements.extend(elements)
                    
                    # Sleep after success to be nice to the server
                    logger.info("Waiting 30 seconds before next region to prevent rate limit...")
                    await asyncio.sleep(30)
                    break # Success, move to next region
                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 429:
                        wait_time = 60 * (attempt + 1)
                        logger.warning(f"Hit 429 Rate Limit for {region_name}. Server is blocking us. Waiting {wait_time} seconds before retrying...")
                        await asyncio.sleep(wait_time)
                    else:
                        logger.error(f"Failed to fetch {region_name} from Overpass API: {e}")
                        break # Other HTTP error, skip this region
                except Exception as e:
                    logger.error(f"Failed to fetch {region_name}: {e}")
                    break # Other error, skip this region
                
    return all_elements
