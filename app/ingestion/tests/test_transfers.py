from app.ingestion.curated.transfers import (
    _is_valid_transjakarta_transfer,
    _supports_spatial_transfer,
)


def test_accepts_named_and_curated_transfers_only_within_reviewed_distance() -> None:
    assert _is_valid_transjakarta_transfer("krl:cawang", "Cawang", "St. Cawang 2", 21)
    assert _is_valid_transjakarta_transfer("mrt:asean", "ASEAN", "CSW 1", 142)
    assert not _is_valid_transjakarta_transfer("krl:tanjung-barat", "Tanjung Barat", "H. Alwi", 30)
    assert not _is_valid_transjakarta_transfer("mrt:asean", "ASEAN", "CSW 1", 700)


def test_spatial_transfers_only_connect_different_modes_to_local_services() -> None:
    assert _supports_spatial_transfer("angkot", "transjakarta")
    assert _supports_spatial_transfer("bikun", "krl")
    assert not _supports_spatial_transfer("angkot", "angkot")
    assert not _supports_spatial_transfer("transjakarta", "transjakarta")
    assert not _supports_spatial_transfer("mrt", "transjakarta")
