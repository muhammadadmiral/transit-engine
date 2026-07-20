import os

import pytest
from fastapi.testclient import TestClient
from dotenv import load_dotenv

from app.main import app


pytestmark = pytest.mark.integration
load_dotenv()


def test_live_network_layers_and_representative_multimodal_routes() -> None:
    if not os.environ.get("DATABASE_URL"):
        pytest.skip("DATABASE_URL is not configured")

    client = TestClient(app)
    stops = client.get("/network/stops", params={"mode": "krl", "limit": 500})
    assert stops.status_code == 200
    assert stops.json()["total"] == 82

    geometry = client.get("/network/routes/mrt:north-south/geometry")
    assert geometry.status_code == 200
    assert all(len(feature["geometry"]["coordinates"]) > 2 for feature in geometry.json()["features"])

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
        assert response.status_code == 200, response.text
        assert response.json()["options"]
        assert any(
            segment["mode"] == "walk"
            for option in response.json()["options"]
            for segment in option["segments"]
        )
