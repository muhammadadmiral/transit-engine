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
    dataset = parse_osm_relations([source, source], verified_at=date(2026, 7, 20))

    assert dataset.stops and dataset.segments
    assert len({segment.id for segment in dataset.segments}) == len(dataset.segments)
    assert all(len(stop.id) <= 120 for stop in dataset.stops)
    assert all(len(segment.id) <= 120 for segment in dataset.segments)
    assert all(segment.mode is TransportMode.ANGKOT for segment in dataset.segments)
    assert all(segment.service_category is ServiceCategory.FEEDER for segment in dataset.segments)
    assert all(segment.data_confidence is DataConfidence.COMMUNITY for segment in dataset.segments)


def test_parser_rejects_unrelated_generic_bus() -> None:
    dataset = parse_osm_relations(
        [
            relation(1, route="bus", name="TransJakarta BRT 1"),
            relation(2, route="bus", name="Angkot K02"),
        ]
    )

    assert dataset.segments
    assert all("TransJakarta" not in segment.service_name for segment in dataset.segments)


def test_extracts_a_short_display_code_when_osm_ref_is_missing() -> None:
    assert _display_route_code("37 : Kp Rambutan - Cibinong", "37 : Kp Rambutan - Cibinong") == "37"
    assert (
        _display_route_code("Angkot U02 : Tg Priuk - Embrio", "Angkot U02 : Tg Priuk - Embrio")
        == "U02"
    )
