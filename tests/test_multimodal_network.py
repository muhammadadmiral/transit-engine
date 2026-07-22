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
        assert bikun_stops.json()["total"] == 19

        angkot_stops = client.get("/network/stops", params={"mode": "angkot", "limit": 1})
        assert angkot_stops.status_code == 200
        # Angkot is a continuous hail-and-ride corridor, never persisted as fake stops.
        assert angkot_stops.json()["total"] == 0

        nearby = client.get(
            "/stops/nearby",
            params={
                "lat": -6.360531,
                "lng": 106.831775,
                "radiusMeters": 500,
                "purpose": "origin",
                "limit": 10,
            },
        )
        assert nearby.status_code == 200
        nearby_items = nearby.json()
        assert nearby_items
        assert nearby_items == sorted(nearby_items, key=lambda item: item["distanceMeters"])
        assert all(item["canBoard"] for item in nearby_items)
        assert any(item["id"] == "bikun:stasiun-ui" for item in nearby_items)

        empty_nearby = client.get(
            "/stops/nearby",
            params={"lat": 0, "lng": 0, "radiusMeters": 50},
        )
        assert empty_nearby.status_code == 200
        assert empty_nearby.json() == []

        unknown_origin = client.post(
            "/route-search",
            json={
                "originStopId": "not:a:real:stop",
                "destinationStopId": "krl:bogor",
            },
        )
        assert unknown_origin.status_code == 404

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
        coordinates = geometry["features"][0]["geometry"]["coordinates"]
        first_lng, first_lat = coordinates[0]
        last_lng, last_lat = coordinates[-1]
        angkot_route = client.post(
            "/route-search",
            json={
                "originLat": first_lat,
                "originLng": first_lng,
                "destinationLat": last_lat,
                "destinationLng": last_lng,
                "accessRadiusMeters": 500,
                "maxTransfers": 0,
            },
        )
        assert angkot_route.status_code == 200
        assert all(
            any(segment["mode"] == "angkot" for segment in option["segments"])
            for option in angkot_route.json()["options"]
        )
        assert all(
            option["fareQuote"]["status"] == "range" for option in angkot_route.json()["options"]
        )

        # Real coordinate regressions: routing must consider the closest useful
        # station/corridor, not just the nearest fixed stop.
        sman_to_sawangan = client.post(
            "/route-search",
            json={
                "originLat": -6.3361189,
                "originLng": 106.8358042,
                "destinationLat": -6.4001908,
                "destinationLng": 106.76372,
                "accessRadiusMeters": 1500,
                "maxTransfers": 5,
            },
        )
        assert sman_to_sawangan.status_code == 200
        fastest = next(
            option
            for option in sman_to_sawangan.json()["options"]
            if option["criteria"] == "fastest"
        )
        assert [(segment["mode"], segment["routeCode"]) for segment in fastest["segments"]] == [
            ("walk", "WALK"),
            ("krl", "BOGOR LINE"),
            ("walk", "WALK"),
            ("angkot", "D03"),
            ("walk", "WALK"),
        ]
        assert fastest["segments"][0]["toStopName"] == "Universitas Pancasila"
        assert fastest["segments"][3]["trafficSource"] == "historical_profile"
        angkot_feature = next(
            feature
            for feature in fastest["geojson"]["features"]
            if feature["properties"]["mode"] == "angkot"
        )
        assert angkot_feature["properties"]["trafficSource"] == "historical_profile"

        ui_to_gunadarma = client.post(
            "/route-search",
            json={
                "originLat": -6.3628,
                "originLng": 106.824,
                "destinationLat": -6.3539705,
                "destinationLng": 106.8412175,
                "accessRadiusMeters": 1500,
                "maxTransfers": 5,
            },
        )
        assert ui_to_gunadarma.status_code == 200
        modes_and_codes = {
            (segment["mode"], segment["routeCode"])
            for option in ui_to_gunadarma.json()["options"]
            for segment in option["segments"]
        }
        assert ("bikun", "BLUE") in modes_and_codes
        assert ("angkot", "D11") in modes_and_codes

        ft_to_margonda_gate = client.post(
            "/route-search",
            json={
                "originStopId": "bikun:teknik",
                "destinationLat": -6.3593023,
                "destinationLng": 106.8343696,
                "destinationLabel": "Jalan tikus Margonda menuju Kukusan",
                "accessRadiusMeters": 1500,
                "maxTransfers": 5,
            },
        )
        assert ft_to_margonda_gate.status_code == 200
        fastest_gate = next(
            option
            for option in ft_to_margonda_gate.json()["options"]
            if option["criteria"] == "fastest"
        )
        assert [segment["routeCode"] for segment in fastest_gate["segments"]] == [
            "RED",
            "WALK",
            "GATE",
            "WALK",
        ]
        crossing = fastest_gate["segments"][2]
        assert crossing["accessAction"] == "paid_station_crossing"
        assert crossing["walkingRouteSource"] == "curated"
        assert "tap keluar" in crossing["instruction"].casefold()
        bikun_feature = fastest_gate["geojson"]["features"][0]
        assert bikun_feature["properties"]["gradientStart"] == "#FFD43B"
        assert bikun_feature["properties"]["animationDirection"] == "forward"
