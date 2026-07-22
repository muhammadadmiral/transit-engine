"""Fetch and persist the official Kabupaten Bogor angkot GIS layer."""

import asyncio
import json
import sys
from pathlib import Path

import httpx

from app.db.session import SessionLocal
from app.db.transit_writer import replace_flexible_routes
from app.ingestion.official.bogor_angkot import SOURCE_URL, parse_bogor_features
from app.routing.graph_cache import invalidate_graph_cache


async def import_bogor_angkot(paths: list[str] | None = None) -> int:
    payloads = (
        [json.loads(Path(path).read_text()) for path in paths] if paths else await _fetch_payloads()
    )
    routes = parse_bogor_features(payloads)
    if not routes:
        raise RuntimeError("Official Bogor GIS returned no valid angkot corridors")
    async with SessionLocal() as session:
        await replace_flexible_routes(session, routes, route_id_prefix="angkot:bogor-gis:")
        await session.commit()
    invalidate_graph_cache()
    return len(routes)


async def _fetch_payloads() -> list[dict]:
    query_url = f"{SOURCE_URL}/query"
    headers = {"User-Agent": "TransHub-Jabodetabek/0.1"}
    async with httpx.AsyncClient(timeout=180, headers=headers) as client:
        id_response = await client.get(
            query_url,
            params={"where": "1=1", "returnIdsOnly": "true", "f": "json"},
        )
        id_response.raise_for_status()
        object_ids = id_response.json().get("objectIds", [])
        payloads = []
        for index in range(0, len(object_ids), 10):
            response = await client.get(
                query_url,
                params={
                    "objectIds": ",".join(map(str, object_ids[index : index + 10])),
                    "outFields": "*",
                    "returnGeometry": "true",
                    "outSR": "4326",
                    "f": "json",
                },
            )
            response.raise_for_status()
            payloads.append(response.json())
        return payloads


if __name__ == "__main__":
    count = asyncio.run(import_bogor_angkot(sys.argv[1:] or None))
    print(f"Imported {count} official Kabupaten Bogor angkot corridors.")
