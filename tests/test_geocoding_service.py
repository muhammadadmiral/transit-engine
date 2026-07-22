from app.geocoding.service import _from_tomtom, _rank_results
from app.models.schema import GeocodeSource, PlaceResult


def test_tomtom_poi_is_mapped_without_landmark_hardcoding() -> None:
    result = _from_tomtom(
        {
            "address": {
                "freeformAddress": "Jl. Margonda Raya, Depok",
                "municipality": "Depok",
            },
            "id": "provider-poi-id",
            "poi": {
                "classifications": [{"code": "education", "names": [{"name": "University"}]}],
                "name": "Kampus Contoh",
            },
            "position": {"lat": -6.35, "lon": 106.83},
            "type": "POI",
        }
    )

    assert result.label == "Kampus Contoh"
    assert result.area == "Depok"
    assert result.source is GeocodeSource.TOMTOM
    assert result.id == "tomtom:POI:provider-poi-id"


def test_generic_ranking_prefers_the_requested_campus_variant() -> None:
    def place(label: str, identity: str) -> PlaceResult:
        return PlaceResult(
            area="Depok",
            category="university",
            id=identity,
            label=label,
            lat=-6.35,
            lng=106.83,
            subtitle="Kelapa Dua, Jawa Barat",
            source=GeocodeSource.PHOTON,
        )

    results = _rank_results(
        "Universitas Contoh Kampus E Kelapa Dua Depok",
        [place("Universitas Contoh Kampus K", "k"), place("Universitas Contoh Kampus E", "e")],
    )

    assert results[0].id == "e"
