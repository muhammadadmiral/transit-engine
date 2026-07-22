from app.ingestion.curated.angkot_depok import ROUTES, build_depok_angkot_routes
from app.models.schema import DataConfidence, TransportMode


def test_depok_corridors_are_directed_and_cover_priority_destinations() -> None:
    routes = build_depok_angkot_routes()
    route_codes = {route.route_code for route in routes}

    assert route_codes == {"D03", "D11"}
    assert {route.code for route in ROUTES} == route_codes
    assert all(route.mode is TransportMode.ANGKOT for route in routes)
    assert all(route.data_confidence is DataConfidence.COMMUNITY for route in routes)
    assert all(len(route.id) <= 120 for route in routes)

    d03_points = [
        point for route in routes if route.route_code == "D03" for point in route.coordinates
    ]
    assert any(abs(point[0] - 106.76372) < 0.02 for point in d03_points)

    d11_points = [
        point for route in routes if route.route_code == "D11" for point in route.coordinates
    ]
    assert any(
        abs(point[1] - (-6.3539705)) < 0.002 and abs(point[0] - 106.8412175) < 0.002
        for point in d11_points
    )


def test_each_curated_route_can_be_travelled_in_both_directions() -> None:
    routes = build_depok_angkot_routes()
    by_code = {}
    for route in routes:
        by_code.setdefault(route.route_code, []).append(route.coordinates)
    assert all(len(directions) == 2 for directions in by_code.values())
    assert all(directions[0] == list(reversed(directions[1])) for directions in by_code.values())
