import os

import pytest
from dotenv import load_dotenv
from fastapi.testclient import TestClient

from app.main import app
from app.routing.graph_cache import invalidate_graph_cache

pytestmark = pytest.mark.integration
load_dotenv()


def test_live_network_layers_and_representative_multimodal_routes() -> None:
    if not os.environ.get("DATABASE_URL"):
        pytest.skip("DATABASE_URL is not configured")

    invalidate_graph_cache()
    with TestClient(app) as client:
        stops = client.get("/network/stops", params={"mode": "krl", "limit": 500})
        assert stops.status_code == 200
        assert stops.json()["total"] == 82

        bikun_stops = client.get("/network/stops", params={"mode": "bikun", "limit": 500})
        assert bikun_stops.status_code == 200
        assert bikun_stops.json()["total"] == 10

        angkot_stops = client.get("/network/stops", params={"mode": "angkot", "limit": 1})
        assert angkot_stops.status_code == 200
        assert angkot_stops.json()["total"] > 0

        geometry = client.get("/network/routes/mrt:north-south/geometry")
        assert geometry.status_code == 200
        assert all(
            len(feature["geometry"]["coordinates"]) > 2 for feature in geometry.json()["features"]
        )

        cases = (
            ("krl:bogor", "lrt-jabodebek:jatimulya", 1),
            ("mrt:lebak-bulus", "lrt-jabodebek:jatimulya", 1),
            ("lrt-jakarta:pegangsaan-dua", "mrt:bundaran-hi", 5),
        )
        for origin, destination, max_transfers in cases:
            response = client.post(
                "/route-search",
                json={
                    "originStopId": origin,
                    "destinationStopId": destination,
                    "maxTransfers": max_transfers,
                },
            )
            assert response.status_code == 200, f"{origin} -> {destination}: {response.text}"
            assert response.json()["options"]
            assert any(
                segment["mode"] == "walk"
                for option in response.json()["options"]
                for segment in option["segments"]
            )

        bikun_route = client.post(
            "/route-search",
            json={
                "originStopId": "bikun:stasiun-ui",
                "destinationStopId": "bikun:menwa",
                "maxTransfers": 0,
            },
        )
        assert bikun_route.status_code == 200
        assert all(
            option["fareQuote"]["estimatedAmount"] == 0 for option in bikun_route.json()["options"]
        )

        routes = client.get("/network/routes", params={"mode": "angkot", "limit": 1})
        route_id = routes.json()["items"][0]["id"]
        geometry = client.get(f"/network/routes/{route_id}/geometry").json()
        first_segment = geometry["features"][0]["properties"]
        angkot_route = client.post(
            "/route-search",
            json={
                "originStopId": first_segment["fromStopId"],
                "destinationStopId": first_segment["toStopId"],
                "maxTransfers": 0,
            },
        )
        assert angkot_route.status_code == 200
        assert all(
            option["fareQuote"]["status"] == "range" for option in angkot_route.json()["options"]
        )
