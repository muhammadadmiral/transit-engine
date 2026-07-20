# 📄 PROJECT BLUEPRINT & PRD: TRANSHUB-JABODETABEK

**Project Name:** TransHub Jabodetabek

**Target Domain:** *(belum ditentukan)*

**Platform:** Modern Web Application (Multi-Modal Trip Planner) — arsitektur **dua service terpisah**

**Core Focus:** Graph Routing Engine, Geographic Map Visualization, Multi-Source Data Aggregation, Transparent Fare Calculation

**Repositori:**
* [`transhub-web`](#) — Next.js, UI, peta, presentasi. Repo ini juga menyimpan dokumen ini (`blueprint.md`) sebagai pusat kebenaran arsitektur lintas-repo.
* [`transit-engine`](#) — FastAPI (Python), domain logic: routing engine, data ingestion, database.

**Companion Docs:** `transhub-web/agent-guide.md` (design system + aturan build frontend) · `transit-engine/agent-guide.md` (aturan build backend) · `transhub-web/README.md` (public-facing overview)

**Document Status:** Draft (v2.0 — revisi arsitektur split-service)

---

## 1. Executive Summary

### 🚨 Problem Statement

Naik transportasi umum di Jabodetabek membingungkan untuk orang awam dan komuter baru. Aplikasi resmi tiap operator (JakLingko, KRL Access, MRT Jakarta) berdiri sendiri-sendiri — infonya terpisah per moda, kaku, dan tidak pernah menjawab pertanyaan sebenarnya yang orang punya: **"dari titik A ke titik B, naik apa yang paling murah/paling cepat, dan di mana harus pindah?"**

### 💡 The Solution (TransHub Jabodetabek)

TransHub menjawab pertanyaan itu langsung: input titik asal & tujuan, sistem menghitung **rute kombinasi lintas moda** (mis. TransJakarta sambung KRL sambung angkot) lengkap dengan total tarif dan estimasi waktu tempuh, ditampilkan di atas peta geografis asli dengan jalur tiap moda diberi warna berbeda.

> **Perbedaan mendasar dari proyek "Harga Sembako":** ini bukan aplikasi *fetch-and-display*. Inti produk ini adalah **mesin routing di atas graph** (stasiun/halte = simpul, rute = sisi berbobot waktu+biaya), mirip skala masalah Google Maps Transit — bukan CRUD data harga. Ini konsekuensi ke seluruh arsitektur di bawah, termasuk keputusan memisahkan domain logic ke service Python tersendiri (§5).

### ⚠️ Risiko Utama yang Harus Disadari dari Awal

1. **Angkot tidak punya data terpusat resmi.** Tidak ada GTFS atau *open data* pemerintah untuk trayek angkot se-Jabodetabek. Ini risiko tertinggi di proyek ini — lihat §8.6 untuk strategi konkretnya, jangan anggap ini "detail nanti".
2. **Kualitas data angkot akan tidak konsisten.** Trayek KRL/MRT/TransJakarta bersifat resmi dan stabil; trayek angkot sering berubah tanpa pengumuman. Sistem harus dirancang menerima bahwa cakupan angkot **parsial dan perlu diberi label kepercayaan data** ke pengguna (§8.4).
3. **Skala graph nyata:** sistem transit terintegrasi Jabodetabek mencakup puluhan lin dan ratusan stasiun/halte. Bukan graph kecil yang bisa dihitung naif di client — perhitungan rute harus di server, dan sekarang di service terpisah (§5).
4. **Dua service = dua titik kegagalan.** Latency lintas-service dan strategi anti cold-start (§12) bukan detail infra yang bisa diabaikan — kalau `transit-engine` sleep/lambat, seluruh fitur inti produk berhenti berfungsi.

---

## 2. Target Audience

* **Komuter Baru / Pendatang:** Baru pindah ke Jabodetabek atau baru mulai kerja, belum familiar dengan sistem transportasi kota, butuh instruksi "naik apa, di mana pindah" yang jelas.
* **Wisatawan Domestik:** Ke Jakarta untuk kebutuhan tertentu, tidak familiar dengan JakLingko/KRL Access, butuh rute yang dijelaskan dengan bahasa awam.
* **Komuter Reguler yang Cari Alternatif:** Ingin membandingkan opsi (lebih murah vs lebih cepat) yang tidak ditampilkan aplikasi resmi tiap operator.

---

## 3. Design Philosophy & Signature Interaction

Sistem desain lengkap (palet, tipografi, motion) ada di `transhub-web/agent-guide.md`. Ringkasan arah:

**Arah visual:** Subjek nyata di sini adalah **jaringan/rute/perpindahan** itu sendiri — bukan tema "pasar". Referensi: peta rute transit klasik, papan informasi stasiun, kartu elektronik (JakLingko/e-money), rambu penunjuk arah.

**Signature element — "Jalur Hidup" (Living Route Line):** setelah rute dihitung, jalur di peta digambar berurutan segmen-demi-segmen, masing-masing "menyala" saat gilirannya, disertai efek kamera (`pitch`/`bearing`/`flyTo` MapLibre) yang mengikuti arah perjalanan — bukan 3D building/terrain literal, murni animasi kamera sinkron dengan GSAP timeline. Titik transit ditandai jelas dengan indikator "pindah di sini".

**Peta:** geografis asli, dioverlay GeoJSON per jalur dengan warna mengikuti identitas visual resmi tiap operator — bukan warna brand TransHub.

---

## 4. UI/UX Core Features

* **Input Titik A → Titik B:** pencarian lokasi (alamat/nama tempat/nama stasiun-halte) lewat geocoding, bukan cuma pilih dari daftar stasiun.
* **Rekomendasi Rute Multi-Kriteria:** dua opsi berdampingan — **"Paling Murah"** dan **"Paling Cepat"**.
* **Rincian Perpindahan (Transit Breakdown):** naik moda apa dari mana, turun di mana, estimasi waktu tunggu di titik transit.
* **Peta Geografis + Overlay Jalur Berwarna:** dengan animasi "Jalur Hidup" (§3), termasuk efek kamera.
* **Transparansi Tarif:** rincian biaya per segmen, termasuk catatan estimasi diskon integrasi antar-moda (JakLingko) kalau berlaku.
* **Label Kepercayaan Data:** badge di tiap segmen angkot yang menandakan data bersumber dari riset manual/komunitas.

---

## 5. Repository & Service Architecture

### 5.1 Kenapa Dipisah Jadi Dua Repo/Service

Awalnya proyek ini direncanakan monolitik di Next.js (Route Handler menjalankan routing engine TypeScript langsung). Keputusan sekarang: **pisahkan domain logic ke service Python (FastAPI) terpisah dari presentasi (Next.js)**. Alasannya bukan sekadar preferensi bahasa:

1. **GTFS processing & graph algorithm punya tooling matang di Python** (`gtfs-kit`, `networkx`) yang jauh lebih siap-pakai daripada ekosistem npm untuk kasus yang sama.
2. **Satu skema data, satu bahasa.** Kalau ingestion dan routing engine sama-sama di Python, skema data (`Stop`/`Route`/`Segment`) cukup didefinisikan sekali sebagai Pydantic model — jadi single source of truth, bukan diduplikasi manual di TS dan Python.
3. **Next.js tetap fokus di kekuatannya**: UI, rendering peta, state management — tanpa perlu menjalankan komputasi graph berat di runtime yang sama dengan rendering halaman.

### 5.2 Pembagian Tanggung Jawab

| | `transhub-web` (Next.js) | `transit-engine` (FastAPI) |
| --- | --- | --- |
| **Isi** | UI, MapLibre rendering, form pencarian, state (Zustand/React Query), animasi | Routing engine (networkx), data ingestion (GTFS + manual angkot), database ownership, GeoJSON generation |
| **Akses Database** | ❌ Tidak pernah langsung | ✅ Satu-satunya pemilik akses Supabase |
| **Deploy** | Vercel | FastAPI Cloud |
| **Bahasa** | TypeScript | Python |

**Aturan tegas:** `transhub-web` tidak pernah connect ke Supabase langsung, bahkan untuk read-only sederhana (mis. autocomplete lokasi) — semua data lewat REST API `transit-engine`. Pengecualian eksplisit: **geocoding** (nama tempat → lat/lng) lewat Nominatim dipanggil langsung dari Next.js Route Handler tipis, karena ini stateless, tidak menyentuh database TransHub, dan tidak melibatkan domain logic apa pun (lihat `transhub-web/agent-guide.md` §12).

> Kalau nanti ada fitur auth (belum direncanakan, statusnya "mungkin di masa depan"), autentikasi tetap lewat endpoint `transit-engine`, bukan jalur DB terpisah di Next.js — supaya prinsip "satu pemilik database" tidak dilanggar di kemudian hari.

### 5.3 Kontrak Komunikasi Antar-Service

* `transhub-web` memanggil `transit-engine` lewat REST/JSON, base URL dari env var `FASTAPI_BASE_URL`.
* Response `/route-search` berupa **GeoJSON `FeatureCollection` siap render** per opsi rute (tercepat/termurah) — `transit-engine` yang merakit geometri, bukan `transhub-web` yang mengolah raw rows.
* Detail type-safety lintas-service ada di §10.

---

## 6. My Role: Solo Fullstack Developer

* **Data Collector & Curator:** mengumpulkan, membersihkan, dan menstrukturkan data dari GTFS resmi dan hasil riset manual angkot ke satu skema data terpadu (Pydantic, di `transit-engine`).
* **Graph & Routing Engineer (Python):** merancang model graph transit dan algoritma pencarian rute multi-kriteria dengan `networkx`.
* **Backend Architect (FastAPI):** merancang skema database, endpoint REST, dan strategi caching hasil rute.
* **Frontend & Map Engineer (Next.js):** membangun visualisasi peta interaktif dengan overlay jalur multi-moda dan animasi "Jalur Hidup".
* **State Manager:** Zustand untuk state UI pencarian, React Query untuk hasil perhitungan rute dari `transit-engine`.

---

## 7. Technical Stack & Infrastructure

### 7.1 `transhub-web` (Next.js)

| Layer | Teknologi | Justifikasi |
| --- | --- | --- |
| **Core Framework** | Next.js 14+ (App Router) | Server Components untuk halaman, Route Handler tipis untuk geocoding proxy saja (bukan domain logic). |
| **Peta** | MapLibre GL JS | Fork open-source Mapbox GL, gratis tanpa vendor lock-in. Peta geografis asli dengan zoom/pan nyata. |
| **Styling** | Tailwind CSS, Headless UI | WAI-ARIA compliant. |
| **Animasi** | Framer Motion (micro-interaction) + GSAP (sekuens "Jalur Hidup", termasuk efek kamera MapLibre) | |
| **State & Fetching** | Zustand (UI state) + TanStack React Query (hasil pencarian rute dari `transit-engine`) | |
| **Validasi Input** | Zod — **hanya untuk form input pengguna**, bukan untuk mendefinisikan ulang bentuk response API | Lihat §10 soal kenapa response API tidak divalidasi ulang pakai Zod. |
| **Tipe API** | Digenerate dari OpenAPI spec `transit-engine` (§10) | |
| **Deployment** | Vercel | |

### 7.2 `transit-engine` (FastAPI)

| Layer | Teknologi | Justifikasi |
| --- | --- | --- |
| **Core Framework** | FastAPI (Python 3.11+) | Auto-generate OpenAPI spec dari Pydantic model — jadi kontrak API otomatis, bukan dokumentasi manual yang gampang basi. |
| **Graph & Pathfinding** | `networkx` | Dijkstra/A* built-in dengan custom weight function. Skala graph Jabodetabek (ratusan simpul) tidak butuh graph library C-based; kompleksitas `igraph` tidak sepadan untuk MVP. |
| **GTFS Parsing** | `gtfs-kit` | High-level, dibangun di atas pandas & shapely, ada validasi feed built-in — dibanding `partridge` yang lebih low-level, `gtfs-kit` lebih cepat untuk solo dev dengan waktu terbatas. |
| **Data Model & Validasi** | Pydantic | Satu-satunya definisi skema `Stop`/`Route`/`Segment`/response API di seluruh proyek — bukan didefinisikan ulang di TypeScript. |
| **Database Access** | SQLAlchemy (async) + `asyncpg` | Satu-satunya service yang connect ke Supabase. |
| **Database** | Supabase (PostgreSQL + PostGIS) | PostGIS untuk query geografis (jarak terdekat titik ke stasiun/halte) di level database. |
| **Migrasi Skema DB** | Alembic | Standar de-facto SQLAlchemy, wajib dipakai daripada ubah skema manual lewat Supabase dashboard — supaya perubahan skema tertelusuri di git. |
| **LLM-assisted Extraction** | Anthropic/OpenAI API (opsional, bantu ekstraksi data angkot dari teks tak terstruktur) | Lihat §8.6 — ini alat bantu riset, bukan pengganti riset. |
| **Testing** | `pytest` | Wajib untuk `routing/` (domain logic kritis). |
| **Lint & Format** | `ruff` + `black` | Setara Biome di sisi TypeScript. |
| **Local Dev** | Docker Compose (FastAPI + Postgres lokal) | Supaya kontributor tidak perlu setup Python env manual + gampang reset state DB. |
| **Deployment** | FastAPI Cloud | Managed FastAPI deployment with Supabase integration and scale-to-zero. |

### 7.3 Utility Bersama (referensi, masing-masing repo pilih versi bahasanya)

* Format tanggal/angka: `date-fns`/`Intl.NumberFormat` (TS), `babel`/format bawaan Python (Python).
* Class merging: `clsx` + `tailwind-merge` (TS only, tidak relevan di backend).

---

## 8. Data Source Strategy (Paling Kritis di Proyek Ini)

### 8.1 Ringkasan Sumber per Moda

| Moda | Status Data | Sumber |
| --- | --- | --- |
| **KRL Commuterline** | Resmi, terstruktur | Feed GTFS KAI Commuter (verifikasi versi terbaru saat mulai development) |
| **MRT Jakarta** | Resmi, terstruktur | Feed GTFS MRT Jakarta |
| **TransJakarta** | Resmi & tervalidasi | Feed GTFS terdaftar di Transitland (`f-transjakarta~id`), tervalidasi lewat Canonical GTFS Schedule Validator (TUMI Datahub). Data halte tambahan di Open Data Pemprov DKI (`satudata.jakarta.go.id`). |
| **LRT Jabodebek** | Kemungkinan belum selengkap moda lain | Cek ketersediaan GTFS resmi dulu; kalau tidak ada, riset manual dengan prioritas lebih tinggi dari angkot (jumlah lin jauh lebih sedikit). |
| **Angkot** | **Tidak ada data resmi terpusat** | Lihat §8.6 — pipeline khusus, bukan sekadar "riset manual" satu baris. |

### 8.2 Kenapa GTFS, Bukan Reverse-Engineering

KRL, MRT, dan TransJakarta punya **GTFS** — format standar industri yang dirancang untuk dikonsumsi pihak ketiga. Prioritaskan sumber GTFS resmi/terdaftar (Transitland, TUMI Datahub, situs resmi operator) di atas scraping — lebih stabil, lebih legal secara niat, lebih mudah diupdate berkala.

### 8.3 Model Data Terpadu

Semua sumber (GTFS maupun manual) **wajib dinormalisasi ke satu skema Pydantic** di `transit-engine`, sebelum masuk database. Skema inilah yang secara otomatis menjadi kontrak OpenAPI dan diturunkan jadi tipe TypeScript di `transhub-web` (§10).

```
Stop { id, name, lat, lng, mode[] }         # simpul graph — bisa multi-moda (interchange)
Route { id, mode, name, color, stops[] }    # definisi 1 rute/trayek per moda
Trip / Schedule { routeId, stopId, arrivalTime, departureTime }  # hanya moda berjadwal (KRL/MRT/TJ)
Segment { fromStopId, toStopId, mode, avgDurationMin, fare, dataConfidence, lastVerifiedAt }
```

### 8.4 Kebijakan Kepercayaan Data (Data Trust Policy)

Setiap `Segment` punya atribut **`dataConfidence: 'official' | 'community'`**:

* `official`: dari GTFS resmi/terdaftar (KRL, MRT, TransJakarta).
* `community`: hasil riset manual (angkot, dan LRT kalau terpaksa manual).

UI **wajib menampilkan label ini** — bagian dari kejujuran produk, bukan detail teknis tersembunyi.

### 8.5 Kebijakan Update Data

* GTFS (KRL/MRT/TransJakarta): proses ulang berkala (bulanan, atau saat operator umumkan perubahan) — bukan realtime.
* Angkot/manual: review berkala manual (mis. tiap 3 bulan, atau saat ada laporan pengguna). Sediakan mekanisme sederhana bagi pengguna untuk melaporkan trayek yang salah (form/link sederhana, bukan sistem crowdsourcing penuh di MVP).

### 8.6 Data Collection Pipeline — Angkot (Critical Path)

Ini bagian tersulit di proyek ini dan **harus direncanakan sebagai proses, bukan satu task development**. Beberapa keputusan sadar:

**Cakupan MVP dibatasi, bukan "se-Jabodetabek":** prioritaskan trayek angkot yang **menghubungkan ke titik transit resmi bervolume tinggi** — stasiun KRL besar dan halte TransJakarta koridor utama. Ini bagian "last-mile" yang paling sering dibutuhkan pengguna dan paling feasible dikerjakan solo, dibanding klaim cakupan penuh yang mustahil untuk satu orang dan justru berisiko menampilkan data salah.

**Kenapa tidak "training AI model" untuk data trayek:** tidak ada dataset trayek angkot berlabel dalam jumlah cukup untuk melatih model prediksi rute — dan kalaupun ada datanya, itu berarti datanya sudah tersedia, tidak perlu model lagi. Trayek angkot adalah **fakta lapangan** (kendaraan nomor sekian lewat jalan A-B-C, tarif segini), bukan sesuatu yang bisa diprediksi dari pola statistik. Domain masalahnya adalah pengumpulan fakta, bukan prediksi.

**Alur pipeline yang benar:**

1. **Kumpulkan sumber mentah tak terstruktur** — forum komuter, grup Facebook/Telegram, review Google Maps yang menyebut nomor trayek/rute/tarif, dan cek `soluvas/gtfs-indonesia` di GitHub sebagai titik awal sebelum riset dari nol.
2. **Ekstraksi dibantu LLM** — teks mentah ("naik KWK 02 dari Citeureup ke Cibinong, ongkos 5rb") diekstrak jadi baris terstruktur (`kodeTrayek`, `dari`, `ke`, `estimasiTarif`, `sumberURL`) memakai LLM API. Ini **alat bantu ekstraksi**, bukan pengganti sumber — setiap baris hasil ekstraksi tetap harus punya `sumberURL` yang bisa ditelusuri balik, dan LLM tidak pernah dipakai untuk "mengarang" trayek yang tidak ada sumbernya.
3. **Validasi manual** — cross-check hasil ekstraksi dengan Google Maps (rute jalan yang masuk akal) dan, kalau memungkinkan, observasi lapangan langsung untuk trayek prioritas tertinggi.
4. **Normalisasi ke skema terpadu** — masuk lewat adapter `data-ingestion/manual/angkot.py` di `transit-engine`, dengan `dataConfidence: 'community'` dan `lastVerifiedAt` diisi tanggal validasi, bukan tanggal ekstraksi.
5. **Publikasikan dengan jujur soal cakupan** — UI harus bisa menunjukkan area/koridor mana yang belum tercover, bukan diam-diam menampilkan hasil rute yang "melompat" karena data angkotnya tidak ada.

Rencanakan waktu riset ini secara eksplisit dan terpisah dari waktu development — ini pekerjaan riset yang memakan waktu kalender nyata, bukan sekadar "tulis kode lebih lama".

---

## 9. Routing Engine — Prinsip Desain

* **Dihitung di server (`transit-engine`), selalu.** Graph mencakup puluhan lin dan ratusan simpul — tidak pantas dihitung di browser maupun di Next.js.
* **Multi-kriteria, bukan satu skor gabungan buatan.** Hitung rute "paling cepat" dan "paling murah" sebagai dua pemanggilan `networkx` shortest-path terpisah dengan fungsi bobot (`weights.py`) berbeda, bukan digabung jadi satu angka skor yang menyembunyikan trade-off.
* **Batasi jumlah transit sebagai parameter (`max_transfers`)**, bukan hardcode tersebar di kode.
* **Cache hasil untuk pasangan asal-tujuan yang sering dicari** — karena graph tidak berubah harian, simpan hasil di tabel cache Postgres (bukan Redis — sesuai constraint budget $0) dengan TTL panjang, dikunci per `(origin, destination, criteria)`.
* **`pathfinder.py` adalah domain logic murni** — fungsi `(graph, origin, destination, criteria) -> RouteOption[]` yang bisa ditest dengan `pytest` tanpa perlu menjalankan FastAPI sama sekali.

---

## 10. API Contract & Type Safety Lintas-Service

Karena domain logic dan presentasi sekarang di dua bahasa berbeda, kontrak API adalah titik paling rawan drift. Solusinya:

1. **Pydantic model di `transit-engine` adalah satu-satunya source of truth** untuk bentuk data (`Stop`, `Route`, `Segment`, response `/route-search`, dll).
2. **FastAPI auto-generate OpenAPI spec** dari Pydantic model tersebut, tersedia di `/openapi.json` (dan UI interaktif di `/docs`).
3. **`transhub-web` men-generate TypeScript types dari OpenAPI spec itu** (pakai `openapi-typescript` atau setara), lewat script (`npm run generate-types`), dijalankan tiap kali kontrak API berubah.
4. **Zod di `transhub-web` hanya untuk validasi form input pengguna** (origin/destination/kriteria) — tidak pernah dipakai untuk mendefinisikan ulang bentuk response API.

Ini menggantikan pola lama "satu skema Zod di `data-ingestion/schema.ts`" — sekarang levelnya lintas-repo, tapi prinsipnya sama: satu definisi tipe, tidak diduplikasi manual.

---

## 11. Performance & Accessibility Budget

* **Render layer jalur secara progresif** — jangan muat semua rute se-Jabodetabek sekaligus.
* **Simplifikasi geometri GeoJSON** untuk zoom rendah — `transit-engine` yang bertanggung jawab menyederhanakan geometri sebelum dikirim (bukan tugas Next.js mengolah ulang).
* **Tile map ringan** — pilih provider tile yang dioptimasi ukuran.
* **Latensi lintas-service adalah bagian dari performance budget** — setiap pencarian rute berarti Vercel memanggil FastAPI Cloud lewat network. Endpoint `/route-search` harus dites end-to-end untuk waktu respons realistis, bukan diasumsikan instan seperti computation lokal.
* GSAP dan Framer Motion tidak pernah dipasang di elemen DOM yang sama, `prefers-reduced-motion` dihormati — detail lengkap di `transhub-web/agent-guide.md`.

---

## 12. Deployment & Infrastructure

Constraint eksplisit: **budget $0**, cuma biaya domain.

| Komponen | Platform | Catatan |
| --- | --- | --- |
| `transhub-web` | Vercel (Hobby) | Standar Next.js deployment. |
| `transit-engine` | FastAPI Cloud | Managed deployment; instances can scale to zero when idle. |
| Database | Supabase (free tier) | Diakses eksklusif dari `transit-engine`. |

**Deploy & migration:** workflow GitHub Actions menjalankan Alembic migration sebelum deploy ke FastAPI Cloud. Cache graph tidak boleh hanya hidup di memori atau filesystem instance, karena instance dapat dihentikan dan dibuat ulang.

**CORS:** `transit-engine` harus eksplisit whitelist origin Vercel (`transhub-web`) di FastAPI CORS middleware — jangan `allow_origins=["*"]` di production meskipun tidak ada data sensitif user, karena endpoint compute-heavy tanpa rate-limit bisa disalahgunakan pihak lain kalau CORS terbuka penuh.

---

## 13. Project Scope (MVP vs Future Scalability)

### 🟢 Fase 1: Minimum Viable Product

* Input titik asal-tujuan, rekomendasi 2 opsi rute (tercepat & termurah).
* Cakupan moda: KRL, MRT, LRT, TransJakarta (GTFS resmi) + angkot **koridor prioritas** yang connect ke titik transit resmi volume tinggi (§8.6), dengan label `community` yang jelas.
* Peta geografis dengan overlay jalur berwarna per moda + animasi "Jalur Hidup" (termasuk efek kamera).
* Rincian tarif & waktu per segmen, tanpa sistem akun/login.
* `transit-engine` live di FastAPI Cloud dengan Supabase sebagai sumber data persisten.

### 🟡 Fase 2: Growth & Optimization

* Perluasan cakupan angkot ke koridor sekunder.
* Mekanisme laporan pengguna untuk koreksi data trayek angkot.
* Programmatic SEO untuk halaman rute populer.
* Riwayat pencarian lokal (client-side saja, tanpa akun).
* Evaluasi ulang infra kalau traffic naik melampaui kapasitas atau kebutuhan FastAPI Cloud.

### 🔴 Fase 3: Advanced Scale

* Estimasi waktu tempuh mempertimbangkan jam sibuk.
* Integrasi status real-time resmi (kalau operator membuka akses).
* Mode "akun" untuk simpan rute favorit — kalau ini terjadi, autentikasi tetap lewat `transit-engine` (§5.2).
* Crowdsourcing terverifikasi untuk update data angkot.

---

*Dokumen ini hidup — kalau agent (di repo mana pun) menemukan keputusan yang tidak tercakup di sini, terutama soal kontrak API atau kualitas data per moda, catat keputusan itu di sini setelah dikonfirmasi developer.*
