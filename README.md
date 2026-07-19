# ⚙️ transit-engine

[![FastAPI](https://img.shields.io/badge/FastAPI-Python%203.11+-009688?style=flat-square&logo=fastapi)](https://fastapi.tiangolo.com)
[![License](https://img.shields.io/badge/license-MIT-lightgrey?style=flat-square)](./LICENSE)

Backend domain-logic service untuk **[TransHub Jabodetabek](https://github.com/username-lu/transhub-web)** — graph routing engine multi-kriteria di atas jaringan transit Jabodetabek (KRL, MRT, LRT, TransJakarta, angkot), plus pipeline data ingestion dari GTFS resmi dan riset manual.

Repo ini **satu-satunya pemilik akses database** di proyek TransHub — frontend ([`transhub-web`](https://github.com/muhammadadmiral/transhub-web)) berkomunikasi dengan repo ini murni lewat REST API.

<!-- > 📌 Arsitektur & PRD lengkap lintas-repo ada di [`blueprint.md`](https://github.com/username-lu/transhub-web/blob/main/blueprint.md) (repo `transhub-web`). Konvensi kode & aturan build khusus repo ini ada di [`agent-guide.md`](./agent-guide.md). -->

---

## 🧠 Apa yang Dilakukan Service Ini

* Menghitung rute kombinasi lintas moda **tercepat** dan **termurah** lewat pathfinding graph (`networkx`), bukan skor gabungan tunggal.
* Mem-parsing & menormalisasi feed **GTFS** resmi (KRL, MRT, TransJakarta) ke satu skema data terpadu (`gtfs-kit`).
* Mengelola pipeline data **angkot** dari riset manual + ekstraksi dibantu LLM, dengan label kepercayaan data (`dataConfidence`) di setiap segmen rute.
* Mengembalikan hasil rute sebagai **GeoJSON `FeatureCollection`** siap-render — frontend tidak perlu mengolah data mentah.
* Mempublikasikan kontrak API-nya sebagai **OpenAPI spec**, dikonsumsi frontend untuk generate tipe TypeScript otomatis.

---

## 🛠️ Tech Stack

| Layer | Teknologi |
| --- | --- |
| **Framework** | FastAPI (Python 3.11+) |
| **Graph & Pathfinding** | `networkx` |
| **GTFS Parsing** | `gtfs-kit` |
| **Validasi & Skema** | Pydantic |
| **Database** | Supabase (PostgreSQL + PostGIS) via SQLAlchemy (async) + `asyncpg` |
| **Migrasi Skema** | Alembic |
| **Testing** | `pytest` |
| **Lint & Format** | `ruff`, `black` |
| **Deployment** | HuggingFace Spaces (Docker SDK) |

---

## 🚀 Local Development

Butuh Docker & Docker Compose.

```bash
git clone https://github.com/username-lu/transit-engine.git
cd transit-engine
cp .env.example .env   # isi credential lokal
docker compose up
```

API berjalan di [http://localhost:8000](http://localhost:8000). Dokumentasi interaktif (Swagger UI) di [http://localhost:8000/docs](http://localhost:8000/docs).

Jalankan migrasi database (sekali di awal / setiap ada perubahan skema):

```bash
docker compose exec api alembic upgrade head
```

Jalankan test suite:

```bash
docker compose exec api pytest
```

---

## 📁 Struktur Proyek (ringkas)

```
app/
├── routers/       # endpoint FastAPI (route_search, stops, data_refresh, health)
├── routing/       # domain logic murni: graph, pathfinder, weights, geojson_builder — WAJIB ditest
├── ingestion/     # adapter GTFS per moda + pipeline data angkot manual/LLM-assisted
├── models/        # schema.py (Pydantic, satu-satunya definisi tipe data) + db_models.py (ORM)
├── db/            # session & migrasi Alembic
└── core/          # config & env var loading
```

<!-- Detail lengkap konvensi & aturan implementasi ada di [`agent-guide.md`](./agent-guide.md). -->

---

## 🌐 Deployment

Service ini di-deploy ke **HuggingFace Spaces** (Docker SDK) karena gratis. Karena Spaces free tier bisa *sleep* setelah idle, repo ini menjalankan **GitHub Actions scheduled workflow** yang melakukan ping berkala ke `GET /health` untuk mencegah cold-start mengganggu pengguna.

---

## ⚠️ Disclaimer

Data dalam service ini berasal dari kombinasi feed GTFS resmi operator dan riset manual komunitas (khusus angkot). Data angkot ditandai eksplisit sebagai non-resmi lewat field `dataConfidence` di setiap respons API dan bisa tidak akurat 100%. Proyek ini independen, tidak berafiliasi dengan operator transportasi manapun.

## 📄 License

MIT — bebas dipakai, dimodifikasi, dan disebarluaskan dengan atribusi.