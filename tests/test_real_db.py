import os

import pytest
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv(".env")


# Tandai ini sebagai tes integrasi yang butuh DB beneran
@pytest.mark.integration
def test_transjabodetabek_real_data_exists():
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        pytest.skip("DATABASE_URL tidak ditemukan di .env, lewati tes integrasi.")

    db_url_sync = db_url.replace("+asyncpg", "")
    engine = create_engine(db_url_sync)

    with engine.connect() as conn:
        res_stops = conn.execute(text("SELECT COUNT(*) FROM stops")).scalar()
        res_segments = conn.execute(text("SELECT COUNT(*) FROM segments")).scalar()

        # Harus ada halte dan rute
        assert res_stops > 0, "Tabel stops kosong!"
        assert res_segments > 0, "Tabel segments kosong!"

        # Cari halte perbatasan
        border_stops = conn.execute(
            text(
                "SELECT name FROM stops "
                "WHERE name ILIKE '%bekasi%' OR name ILIKE '%tangerang%' "
                "OR name ILIKE '%ciputat%' OR name ILIKE '%bogor%' OR name ILIKE '%depok%' "
                "LIMIT 10"
            )
        ).fetchall()

        # Pastikan data perbatasan juga ada
        assert len(border_stops) > 0, "Tidak ada data rute TransJakarta perbatasan (Bodetabek)!"

        print("\n=== HASIL SANITY CHECK DATABASE ===")
        print(f"Total Halte/Stasiun: {res_stops}")
        print(f"Total Segmen Rute  : {res_segments}")
        print("Halte perbatasan terdeteksi:")
        for row in border_stops:
            print(f" - {row[0]}")
