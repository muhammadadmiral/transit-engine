"""Load source-controlled precise rail geometry with a safe straight-line fallback."""

import json
from functools import lru_cache
from pathlib import Path

SNAPSHOT_PATH = Path(__file__).with_name("data") / "rail_geometries.json"


@lru_cache(maxsize=1)
def _geometries() -> dict[str, list[list[float]]]:
    if not SNAPSHOT_PATH.exists():
        return {}
    payload = json.loads(SNAPSHOT_PATH.read_text())
    return payload["segments"]


def segment_geometry(
    route_id: str,
    from_stop_id: str,
    to_stop_id: str,
    fallback: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    direct_key = _key(route_id, from_stop_id, to_stop_id)
    direct = _geometries().get(direct_key)
    if direct:
        return [tuple(point) for point in direct]

    reverse_key = _key(route_id, to_stop_id, from_stop_id)
    reverse = _geometries().get(reverse_key)
    if reverse:
        return [tuple(point) for point in reversed(reverse)]
    return fallback


def _key(route_id: str, from_stop_id: str, to_stop_id: str) -> str:
    return f"{route_id}|{from_stop_id}|{to_stop_id}"
