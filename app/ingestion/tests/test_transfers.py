from app.ingestion.curated.transfers import (
    _is_valid_transjakarta_transfer,
    _supports_spatial_transfer,
)


def test_accepts_named_and_curated_transfers_only_within_reviewed_distance() -> None:
    assert _is_valid_transjakarta_transfer("krl:cawang", "Cawang", "St. Cawang 2", 21)
    assert _is_valid_transjakarta_transfer("mrt:asean", "ASEAN", "CSW 1", 142)
    assert not _is_valid_transjakarta_transfer("krl:tanjung-barat", "Tanjung Barat", "H. Alwi", 30)
    assert not _is_valid_transjakarta_transfer("mrt:asean", "ASEAN", "CSW 1", 700)


def test_persisted_spatial_transfers_exclude_flexible_angkot_corridors() -> None:
    assert not _supports_spatial_transfer("angkot", "transjakarta")
    assert _supports_spatial_transfer("bikun", "krl")
    assert not _supports_spatial_transfer("angkot", "angkot", distance_meters=80)
    assert not _supports_spatial_transfer("angkot", "angkot", distance_meters=121)
    assert _supports_spatial_transfer("transjakarta", "transjakarta", distance_meters=80)
    assert not _supports_spatial_transfer("transjakarta", "transjakarta", distance_meters=121)
    assert not _supports_spatial_transfer("mrt", "transjakarta")
