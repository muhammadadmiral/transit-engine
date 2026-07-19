# 🤖 AGENT GUIDE — transit-engine

Aturan main untuk AI coding agent yang mengerjakan repo **backend** TransHub Jabodetabek. Gaya *guidance + context* — tiap aturan disertai alasan, supaya agent bisa berimprovisasi dengan benar di situasi yang tidak eksplisit diatur di sini.

Repo ini adalah **domain logic layer**: routing engine, data ingestion, dan satu-satunya pemilik akses database. Tidak ada kode UI di sini sama sekali.

Companion docs: [`blueprint.md`](../transhub-web/blueprint.md) (arsitektur & PRD, pusat kebenaran lintas-repo, hidup di repo `transhub-web`) · `transhub-web/agent-guide.md` (aturan repo frontend) · [`README.md`](./README.md) (gambaran teknis repo ini).

---

## 0. Prinsip Inti

1. **Ini proyek graph-routing, bukan CRUD data.** Inti produk adalah mesin pencarian rute di atas graph transit — perhitungan rute adalah domain logic yang harus testable murni tanpa framework, bukan tercampur di dalam route handler FastAPI.
2. **Repo ini satu-satunya pemilik database.** `transhub-web` tidak pernah connect ke Supabase langsung — semua akses lewat endpoint REST repo ini. Jangan desain endpoint yang mengasumsikan caller lain punya akses DB sendiri.
3. **Satu skema Pydantic, dipakai di mana-mana.** GTFS resmi dan data manual angkot harus masuk ke bentuk data yang sama (`Stop`, `Route`, `Segment` — lihat §5) sebelum menyentuh routing engine. Skema ini juga otomatis jadi kontrak OpenAPI yang dikonsumsi `transhub-web` (§7) — jangan buat model response ad-hoc yang tidak lewat skema terpadu.
4. **Routing engine tidak boleh tahu asal data.** `routing/` hanya menerima data dalam bentuk skema terpadu, tidak pernah tahu apakah segmen berasal dari GTFS atau riset manual.
5. **Kejujuran data ke pengguna adalah fitur.** `dataConfidence` wajib ada di setiap `Segment`, tidak boleh opsional atau default tersembunyi.
6. **Response API adalah GeoJSON siap-pakai.** Endpoint `/route-search` mengembalikan `FeatureCollection` yang bisa langsung di-render MapLibre di `transhub-web` — jangan kembalikan raw rows dan menyerahkan perakitan geometri ke frontend.

---

## 1. Struktur Folder (Feature-Based)

```
app/
├── main.py                       # FastAPI app init, CORS, router registration
├── routers/
│   ├── route_search.py           # POST /route-search — endpoint utama
│   ├── stops.py                  # GET /stops — untuk autocomplete di frontend
│   ├── data_refresh.py           # Trigger manual/cron untuk re-proses GTFS berkala
│   └── health.py                 # GET /health — dipakai cron ping anti cold-start
│
├── routing/                      # Domain logic murni, testable tanpa FastAPI sama sekali
│   ├── graph.py                  # bangun graph networkx dari data DB
│   ├── pathfinder.py             # fungsi murni: (graph, origin, destination, criteria) -> RouteOption[]
│   ├── weights.py                # fungsi bobot: waktu vs tarif
│   ├── geojson_builder.py        # rakit RouteOption -> GeoJSON FeatureCollection
│   └── tests/                    # pytest — WAJIB, ini domain logic kritis
│
├── ingestion/
│   ├── gtfs/
│   │   ├── krl_adapter.py
│   │   ├── mrt_adapter.py
│   │   └── transjakarta_adapter.py
│   ├── manual/
│   │   ├── angkot_dataset.py     # hasil riset manual, terstruktur & bersumber jelas
│   │   └── llm_extraction.py     # helper ekstraksi teks-ke-terstruktur (lihat blueprint.md §8.6)
│   └── normalize.py              # ubah tiap sumber jadi skema terpadu
│
├── models/
│   ├── schema.py                 # Pydantic: Stop, Route, Trip/Schedule, Segment — SATU-SATUNYA definisi
│   └── db_models.py               # SQLAlchemy ORM models
│
├── db/
│   ├── session.py                # async engine + session factory (asyncpg)
│   └── migrations/                # Alembic
│
└── core/
    └── config.py                 # env var loading (pydantic-settings)

tests/                             # integration test (test endpoint lewat TestClient)
```

**Kenapa `routing/` terpisah dari `ingestion/`?** Siklus perubahan keduanya beda — data GTFS di-refresh berkala tanpa menyentuh algoritma, dan algoritma routing bisa dioptimasi tanpa menyentuh cara data masuk. Mencampur keduanya bikin perubahan kecil di satu sisi berisiko merembet ke sisi lain.

---

## 2. Konvensi Kode

* **Type hints wajib di semua fungsi** — ini setara "TypeScript strict tanpa `any`" di sisi Python. Pakai `mypy` atau andalkan strict mode editor kalau belum ada waktu setup CI.
* **Pydantic untuk semua boundary data** — input request, output response, dan hasil normalisasi ingestion, semua lewat Pydantic model, bukan `dict` mentah.
* **`ruff` + `black`** untuk lint/format — setara Biome di sisi TypeScript.
* **Conventional Commits**, sama seperti repo frontend.
* **`routing/pathfinder.py` tidak boleh mengimpor apa pun dari FastAPI atau SQLAlchemy.** Kalau fungsi ini butuh data, data itu harus sudah dalam bentuk Python object murni (hasil dari `graph.py`) yang diinject sebagai parameter — bukan query DB di tengah algoritma.

---

## 3. Routing Engine — Aturan Implementasi

* **Domain logic murni, tanpa dependency ke FastAPI.** `pathfinder.py` harus bisa dites dengan `pytest` tanpa server berjalan — fungsi input-output murni: `(graph: nx.Graph, origin: str, destination: str, criteria: Criteria) -> list[RouteOption]`.
* **`networkx` sebagai basis graph & shortest path.** Pakai `nx.dijkstra_path`/`nx.astar_path` dengan custom `weight` callable dari `weights.py`, bukan implementasi Dijkstra dari nol — networkx sudah battle-tested untuk kasus ini, dan skala graph Jabodetabek (ratusan simpul) jauh dari batas performanya.
* **Dua pencarian terpisah untuk "cepat" vs "murah"**, bukan satu skor gabungan (lihat alasan di `blueprint.md` §9) — dua pemanggilan `pathfinder` dengan `weight` function berbeda, bukan percabangan logic di dalam satu fungsi besar.
* **`max_transfers` sebagai parameter fungsi**, bukan angka hardcoded tersebar di kode.
* **`geojson_builder.py` merakit `RouteOption` jadi `FeatureCollection`** sebelum dikembalikan lewat endpoint — `transhub-web` tidak pernah menerima raw graph edges atau koordinat mentah yang perlu dirakit ulang di sisi client.
* **Cache hasil di tabel Postgres**, dikunci `(origin_id, destination_id, criteria)` dengan TTL panjang (graph tidak berubah harian) — bukan cache in-memory saja, karena Space bisa restart/cold-start dan kehilangan cache in-memory.

---

## 4. Data Ingestion — Aturan

### 4.1 GTFS (KRL, MRT, TransJakarta)

* Pakai **`gtfs-kit`** untuk parsing feed `.zip`/`.txt` — jangan tulis parser GTFS manual, formatnya sudah standar dan `gtfs-kit` sudah handle validasi dasar.
* Tiap adapter (`krl_adapter.py`, dst) mengeluarkan data dalam bentuk skema terpadu (§5) — adapter yang tahu detail format sumber, bukan `normalize.py` atau `routing/`.
* Kalau ada sumber baru (mis. LRT ternyata punya GTFS resmi), tambah adapter baru — **jangan modifikasi `routing/` sama sekali**.

### 4.2 Angkot (Manual + LLM-Assisted)

Lihat `blueprint.md` §8.6 untuk strategi lengkap. Aturan implementasi di sini:

* `ingestion/manual/llm_extraction.py` adalah **alat bantu ekstraksi** teks tak terstruktur → baris terstruktur, bukan generator data. Setiap output dari fungsi ini **wajib** membawa field `source_url` yang bisa ditelusuri balik — kalau LLM tidak bisa mengaitkan sebuah baris ke sumber, baris itu tidak boleh masuk ke dataset.
* Data yang sudah diekstrak dan divalidasi manual masuk lewat `angkot_dataset.py` dengan `dataConfidence='community'` dan `lastVerifiedAt` diisi **tanggal validasi manual**, bukan tanggal ekstraksi LLM.
* Prioritaskan trayek yang connect ke stasiun KRL/halte TransJakarta bervolume tinggi — jangan proses seluruh dataset mentah sekaligus tanpa prioritisasi.

### 4.3 Aturan Umum

* **`ingestion/` dan `routing/` tidak saling mengimpor detail internal** — `routing/` hanya menerima data dalam bentuk skema terpadu (`Stop`/`Route`/`Segment`).
* Semua hasil ingestion divalidasi lewat Pydantic model di `models/schema.py` sebelum ditulis ke DB — kegagalan validasi harus eksplisit gagal (raise), bukan silently dropped atau di-null-kan.

---

## 5. Skema Data Terpadu (`models/schema.py`)

```python
from pydantic import BaseModel
from typing import Literal
from datetime import date

class Segment(BaseModel):
    from_stop_id: str
    to_stop_id: str
    mode: Literal["krl", "mrt", "lrt", "transjakarta", "angkot"]
    avg_duration_min: float
    fare: int
    data_confidence: Literal["official", "community"]  # WAJIB
    last_verified_at: date
```

Ini **satu-satunya** definisi tipe data transit di seluruh proyek (dua repo). `routing/` dan `routers/` mengimpor dari sini, tidak mendefinisikan ulang. Model ini juga otomatis membentuk skema OpenAPI (§7) — jangan buat response model paralel yang bentuknya mirip tapi didefinisikan terpisah.

---

## 6. Database

* **SQLAlchemy (async) + `asyncpg`**, koneksi ke Supabase Postgres. Repo ini adalah satu-satunya yang punya credential DB.
* **Alembic untuk migrasi** — perubahan skema selalu lewat migration file yang di-commit ke git, jangan ubah skema manual lewat Supabase dashboard tanpa migration yang menyertainya (kalau terpaksa ubah lewat dashboard untuk eksperimen cepat, generate migration setelahnya untuk menyamakan).
* **PostGIS** dipakai untuk query geografis (jarak titik ke stasiun/halte terdekat) — lakukan di level query database, bukan hitung manual di Python dengan loop semua stops.
* `db_models.py` (SQLAlchemy ORM) dan `schema.py` (Pydantic) **sengaja terpisah** — ORM model untuk persistence, Pydantic model untuk boundary API/validasi. Konversi antara keduanya eksplisit di layer service, bukan mencampur keduanya jadi satu class.

---

## 7. API Contract & OpenAPI

* FastAPI otomatis generate OpenAPI spec dari Pydantic model di `models/schema.py` dan response model tiap router — tersedia di `/openapi.json`, UI interaktif di `/docs`.
* **`transhub-web` men-generate TypeScript types dari spec ini.** Artinya: setiap perubahan pada response model (nama field, tipe, nullable) adalah **breaking change lintas-repo**, bukan cuma perubahan lokal. Sebelum mengubah shape response, pertimbangkan dampaknya ke frontend dan catat di `blueprint.md` §10 kalau perubahannya signifikan.
* **CORS**: whitelist origin domain `transhub-web` secara eksplisit di `main.py`, jangan `allow_origins=["*"]` di production — endpoint compute-heavy tanpa rate-limit rawan disalahgunakan kalau CORS terbuka penuh.

---

## 8. Testing

* **`routing/tests/` wajib ada dan wajib lolos sebelum merge.** Ini domain logic yang kalau salah, hasilnya salah rute ke pengguna — algoritma routing yang salah bisa lolos tanpa ketahuan kalau tidak ditest, beda dari bug UI yang kelihatan visual.
* Pakai `pytest`. Test `pathfinder.py` dengan graph sintetis kecil (bukan selalu data production penuh) supaya test cepat dan deterministik.
* Test ingestion (`ingestion/tests/`) memverifikasi bahwa tiap adapter menghasilkan output yang valid terhadap `models/schema.py` — kalau GTFS feed berubah format, test ini yang harus gagal duluan, bukan ketahuan pas production.

---

## 9. Local Development (Docker Compose)

```yaml
# docker-compose.yml (ringkasan)
services:
  api:
    build: .
    ports: ["8000:8000"]
    env_file: .env
    depends_on: [db]
  db:
    image: postgis/postgis:16-3.4
    environment:
      POSTGRES_PASSWORD: postgres
    ports: ["5432:5432"]
```

* Kontributor cukup `docker compose up`, tidak perlu setup Python env manual atau connect ke Supabase cloud untuk development lokal.
* Migration (`alembic upgrade head`) dijalankan terhadap DB lokal ini, bukan langsung ke Supabase production.
* Kalau butuh data GTFS asli untuk testing lokal, simpan fixture kecil (subset feed) di `tests/fixtures/`, jangan commit feed GTFS penuh ke repo (ukurannya besar dan berubah tiap update).

---

## 10. Deployment (HuggingFace Spaces)

* Space dikonfigurasi dengan **Docker SDK** (bukan Gradio/Streamlit SDK bawaan HF) — `Dockerfile` di root repo yang menjalankan `uvicorn app.main:app`.
* **`GET /health` wajib ada** dan ringan (tidak query DB kalau tidak perlu) — dipakai GitHub Actions scheduled workflow untuk ping berkala anti cold-start (lihat `blueprint.md` §12). Setup workflow ini (`.github/workflows/keep-alive.yml`) adalah bagian dari setup wajib repo ini, bukan opsional.
* Env var production (`DATABASE_URL`, `DATA_REFRESH_SECRET`, dll) diset lewat HuggingFace Spaces secrets, bukan di-commit ke `.env`.

---

## 11. Anti-Patterns — Jangan Lakukan Ini

| ❌ Jangan | ✅ Lakukan Ini |
| --- | --- |
| Query DB di tengah `pathfinder.py` | Data graph diinject sebagai parameter, sudah dalam bentuk Python object |
| Satu skor gabungan "terbaik" yang menyembunyikan trade-off | Dua pencarian terpisah: "tercepat" dan "termurah" |
| Sembunyikan/skip `data_confidence` untuk segmen angkot | Selalu isi field ini, tidak boleh default tersembunyi |
| LLM extraction tanpa `source_url` yang bisa ditelusuri | Setiap baris hasil ekstraksi wajib bisa dilacak ke sumbernya |
| Modifikasi `routing/` tiap kali ada sumber data baru | Tambah adapter baru di `ingestion/`, `routing/` tidak berubah |
| Return raw DB rows dari `/route-search` | Return GeoJSON `FeatureCollection` siap render (§0.6) |
| Ubah skema DB langsung lewat Supabase dashboard tanpa migration | Selalu lewat Alembic migration yang di-commit |
| `allow_origins=["*"]` di CORS production | Whitelist origin `transhub-web` secara eksplisit |
| Cache hasil rute hanya in-memory | Cache di tabel Postgres (survive restart/cold-start) |
| Duplikasi tipe `Stop`/`Route`/`Segment` di beberapa file | Satu Pydantic schema di `models/schema.py` |
| Deploy tanpa `/health` endpoint atau tanpa cron ping | Setup `GET /health` + GitHub Actions keep-alive wajib sebelum go-live |

---

## 12. Environment Variables (Referensi)

```bash
DATABASE_URL=                    # connection string Supabase Postgres (asyncpg)
SUPABASE_SERVICE_ROLE_KEY=       # kalau perlu akses lewat Supabase client selain SQLAlchemy langsung
DATA_REFRESH_SECRET=             # validasi trigger refresh data GTFS berkala
ANTHROPIC_API_KEY=               # atau provider LLM lain, untuk ingestion/manual/llm_extraction.py
CORS_ALLOWED_ORIGIN=             # domain transhub-web di production
```

---

*Dokumen ini hidup — kalau agent menemukan keputusan yang tidak tercakup di sini (terutama soal kualitas/ketersediaan data per moda yang baru diketahui saat development berjalan), catat keputusan itu di `blueprint.md` setelah dikonfirmasi developer.*