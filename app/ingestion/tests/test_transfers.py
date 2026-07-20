from app.ingestion.curated.transfers import _is_valid_transjakarta_transfer


def test_accepts_named_and_curated_transfers_only_within_reviewed_distance() -> None:
    assert _is_valid_transjakarta_transfer("krl:cawang", "Cawang", "St. Cawang 2", 21)
    assert _is_valid_transjakarta_transfer("mrt:asean", "ASEAN", "CSW 1", 142)
    assert not _is_valid_transjakarta_transfer("krl:tanjung-barat", "Tanjung Barat", "H. Alwi", 30)
    assert not _is_valid_transjakarta_transfer("mrt:asean", "ASEAN", "CSW 1", 700)
