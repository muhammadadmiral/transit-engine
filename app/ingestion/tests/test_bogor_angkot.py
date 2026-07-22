from app.ingestion.official.bogor_angkot import parse_bogor_features
from app.models.schema import DataConfidence


def test_official_bogor_polyline_becomes_two_hail_and_ride_directions() -> None:
    payload = {
        "features": [
            {
                "attributes": {
                    "FID": 44,
                    "Keterangan": "Trayek Angkot Ibukota Kabupaten Bogor",
                    "Nama": "Trayek 44 (Citeureup - Babakan Madang)",
                },
                "geometry": {"paths": [[[106.86, -6.56], [106.87, -6.55], [106.88, -6.54]]]},
            },
            {
                "attributes": {
                    "FID": 45,
                    "Keterangan": "Trayek Angkutan Plat Hitam",
                    "Nama": "Trayek 99",
                },
                "geometry": {"paths": [[[106.8, -6.5], [106.81, -6.5]]]},
            },
        ]
    }

    routes = parse_bogor_features([payload])

    assert len(routes) == 2
    assert {route.route_code for route in routes} == {"44"}
    assert all(route.data_confidence is DataConfidence.OFFICIAL for route in routes)
    assert routes[0].coordinates == list(reversed(routes[1].coordinates))
