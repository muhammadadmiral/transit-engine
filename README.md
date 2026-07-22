# Transit Engine

Routing backend untuk **TransHub Jabodetabek**, sebuah perencana perjalanan transportasi publik multimoda. Transit Engine menyatukan jaringan KRL, MRT, LRT, TransJakarta, Mikrotrans, angkot, dan layanan pengumpan lain ke dalam satu graph agar pengguna dapat membandingkan perjalanan tercepat dan termurah.

## Yang dikerjakan

- Menghitung perjalanan lintas moda dan titik perpindahannya.
- Membandingkan opsi tercepat dan termurah sebagai dua perhitungan terpisah.
- Menghitung tarif pada level perjalanan, termasuk tarif flat, matriks origin–destination, band jarak, tarif berbasis waktu, dan rentang estimasi.
- Menyediakan geometri rute yang siap divisualisasikan di peta.
- Menandai asal dan tingkat keyakinan data agar estimasi komunitas tidak terlihat seperti data resmi.

## Cakupan moda

| Moda | Sumber data saat ini | Status tarif |
| --- | --- | --- |
| TransJakarta | GTFS operator | Exact, flat |
| Mikrotrans | GTFS operator, dipisahkan dari bus TransJakarta | Gratis |
| MRT Jakarta | Dataset jaringan dan matriks tarif terkurasi | Exact, origin–destination |
| LRT Jakarta | Dataset jaringan terkurasi | Exact, flat |
| LRT Jabodebek | Dataset jaringan terkurasi | Estimasi berbasis jarak dan waktu |
| KRL Jabodetabek | Topologi dan geometri jaringan terkurasi | Estimasi band jarak |
| Angkot | GIS resmi Kabupaten Bogor, regulasi Depok, dan OSM terverifikasi | Rentang estimasi |
| Bikun UI | Dataset kampus terkurasi | Gratis |

Angkot dimodelkan sebagai koridor *hail-and-ride*, bukan halte fiktif. Titik naik/turun diproyeksikan ke koridor pada runtime sehingga pengguna dapat naik atau turun di bagian jalan yang dilalui. Setiap koridor tetap membawa label `official` atau `community`; harga tidak dipresentasikan sebagai angka pasti.

## Arsitektur

Transit Engine dibangun dengan FastAPI, Pydantic, NetworkX, SQLAlchemy async, Alembic, PostgreSQL, dan PostGIS. Supabase menyimpan jaringan transit; frontend berkomunikasi melalui service ini dan tidak mengakses database secara langsung.

```text
app/
├── routers/       HTTP boundary
├── routing/       graph, pathfinding, weights, dan GeoJSON
├── fares/         journey-level fare engine
├── ingestion/     GTFS, dataset terkurasi, dan OpenStreetMap
├── models/        kontrak domain dan API
└── db/            persistence dan migration
```

## Development

```bash
python -m venv .venv
.venv/bin/pip install -e '.[dev]'
cp .env.example .env
.venv/bin/alembic upgrade head
.venv/bin/pytest -q
```

Docker Compose juga tersedia untuk menjalankan API dan PostGIS secara lokal. Semua perubahan schema wajib melalui Alembic.

## Dokumentasi

- [Product blueprint](./blueprint.md)
- [Data sources and refresh](./docs/DATA_SOURCES.md)
- [Deployment architecture](./DEPLOYMENT.md)
- [Database architecture](./SUPABASE.md)

## Status dan batasan

Proyek ini masih aktif dikembangkan. Jadwal rel memakai frekuensi resmi; ETA moda jalan memakai TomTom Traffic Flow bila key tersedia dan profil waktu yang diberi label bila tidak. Data komunitas dapat tidak lengkap atau berbeda dari kondisi lapangan. TransHub independen dan tidak berafiliasi dengan operator transportasi mana pun.

## License

MIT.
