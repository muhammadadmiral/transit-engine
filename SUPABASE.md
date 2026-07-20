# Database Architecture

Transit Engine memakai Supabase sebagai managed PostgreSQL dengan PostGIS. Database dimiliki eksklusif oleh backend; aplikasi frontend tidak menyimpan credential dan tidak melakukan query Supabase langsung.

## Model data

Jaringan routing dinormalisasi menjadi dua tabel inti:

- `stops` menyimpan identitas, nama, moda, dan titik geografis;
- `segments` menyimpan sisi graph terarah, rute, klasifikasi layanan, durasi, produk tarif, provenance, warna, dan geometri.

Walking transfer juga disimpan sebagai segmen terarah. Konektor rail–TransJakarta berasal dari daftar/alias yang ditinjau, sedangkan proximity matching dibatasi pada layanan lokal yang memang membutuhkan pencocokan spasial. Stop dengan moda sama tidak dihubungkan otomatis hanya karena berdekatan.

## Schema ownership

Alembic adalah satu-satunya otoritas migration aplikasi. Riwayat schema disimpan bersama source code sehingga deployment dapat direproduksi dan ditinjau.

Perubahan schema tidak dilakukan melalui dashboard atau `supabase db push` untuk tabel aplikasi. Supabase CLI boleh dipakai untuk pengelolaan project dan local tooling, tetapi tidak membuat riwayat migration kedua.

## Geospatial data

Semua koordinat memakai WGS84 (`SRID 4326`) dalam urutan longitude, latitude untuk GeoJSON. PostGIS digunakan untuk query kedekatan dalam meter dan index spasial; perhitungan derajat tidak dipakai sebagai pengganti jarak meter.

## Data integrity

- Import per moda berjalan dalam transaksi dan mengganti snapshot lama secara atomik.
- Foreign key memastikan setiap segmen menunjuk stop yang tersedia.
- ID dan field text dibatasi oleh schema database.
- Sumber official dan community tidak disamakan.
- Fare yang tidak pasti disimpan sebagai produk estimasi, bukan angka exact palsu.
- Kegagalan sumber eksternal tidak menghapus snapshot terakhir yang valid.

## Security

- Connection string hanya berada di local environment, CI secret, dan runtime secret manager.
- Frontend hanya mengonsumsi API Transit Engine.
- Database URL, password, access token, dan detail project tidak boleh muncul di log atau dokumentasi publik.
- Backup/restore point diperlukan sebelum migration destruktif atau refresh data production berskala besar.
