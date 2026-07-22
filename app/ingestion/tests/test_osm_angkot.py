from datetime import date

from app.ingestion.osm.parser import _display_route_code, _relation_coordinates, parse_osm_relations
from app.models.schema import DataConfidence, ServiceCategory, TransportMode


def relation(
    relation_id: int, *, route: str = "share_taxi", name: str = "Angkot 01"
) -> dict[str, object]:
    return {
        "id": relation_id,
        "tags": {"route": route, "name": name, "ref": "01"},
        "members": [
            {
                "type": "way",
                "geometry": [
                    {"lon": 106.8000, "lat": -6.2000},
                    {"lon": 106.8100, "lat": -6.2000},
                ],
            },
            {
                "type": "way",
                "geometry": [
                    {"lon": 106.8200, "lat": -6.2000},
                    {"lon": 106.8100, "lat": -6.2000},
                ],
            },
        ],
    }


def test_relation_geometry_reverses_member_to_keep_route_continuous() -> None:
    assert _relation_coordinates(relation(1)) == [
        (106.8, -6.2),
        (106.81, -6.2),
        (106.82, -6.2),
    ]


def test_parser_deduplicates_relations_and_builds_bounded_ids() -> None:
    source = relation(123456789, name="Angkot " + "A" * 200)
    routes = parse_osm_relations([source, source], verified_at=date(2026, 7, 20))

    assert len(routes) == 2
    assert len({route.id for route in routes}) == len(routes)
    assert all(len(route.id) <= 120 for route in routes)
    assert all(route.mode is TransportMode.ANGKOT for route in routes)
    assert all(route.service_category is ServiceCategory.FEEDER for route in routes)
    assert all(route.data_confidence is DataConfidence.COMMUNITY for route in routes)
    assert all(
        route.source_url and "openstreetmap.org/relation" in route.source_url for route in routes
    )
    assert routes[1].coordinates == list(reversed(routes[0].coordinates))


def test_parser_rejects_unrelated_generic_bus() -> None:
    routes = parse_osm_relations(
        [
            relation(1, route="bus", name="TransJakarta BRT 1"),
            relation(2, route="bus", name="Angkot K02"),
        ]
    )

    assert routes
    assert all("TransJakarta" not in route.service_name for route in routes)


def test_extracts_a_short_display_code_when_osm_ref_is_missing() -> None:
    assert _display_route_code("37 : Kp Rambutan - Cibinong", "37 : Kp Rambutan - Cibinong") == "37"
    assert (
        _display_route_code("Angkot U02 : Tg Priuk - Embrio", "Angkot U02 : Tg Priuk - Embrio")
        == "U02"
    )
