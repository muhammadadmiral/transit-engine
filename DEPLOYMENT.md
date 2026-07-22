# Deployment Architecture

Transit Engine dijalankan sebagai aplikasi FastAPI terkelola di FastAPI Cloud. Source code tetap platform-agnostic: entrypoint ASGI didefinisikan di `pyproject.toml`, sedangkan Docker Compose tersedia untuk development lokal.

## Release flow

Repository memiliki dua jalur release:

- `dev` untuk validasi perubahan dan development deployment;
- `main` untuk production.

GitHub Actions menjalankan quality check dan Alembic migration sebelum deployment. Release tidak boleh dilanjutkan jika test atau migration gagal. Credential deployment dan database disimpan sebagai encrypted environment secret dan tidak berada di repository.

## Runtime principles

- Instance aplikasi boleh dihentikan dan dibuat ulang oleh platform.
- Filesystem runtime dianggap ephemeral.
- Supabase/PostgreSQL adalah sumber data persisten.
- Graph cache in-memory adalah optimasi dan harus dapat dibangun ulang dari database.
- Health check ringan tersedia untuk observability, bukan mekanisme keep-alive.
- Origin frontend production diatur eksplisit melalui CORS.

## Schema changes

Alembic migration selalu dijalankan sebelum code yang bergantung pada schema baru. Perubahan yang sulit dibalik dilakukan bertahap: tambah struktur baru, deploy code kompatibel, migrasikan data, lalu hapus struktur lama pada release terpisah.

## Data releases

Dataset transit dirilis terpisah dari schema aplikasi:

- GTFS TransJakarta dapat diperbarui dari sumber operator;
- jaringan rail dan Bikun berasal dari snapshot terkurasi dan terversi;
- angkot resmi Bogor dan Depok disimpan terpisah dari snapshot komunitas OpenStreetMap;
- setiap data refresh diikuti rebuild konektor transfer dan invalidasi/restart graph cache.

Fetcher yang gagal tidak boleh mengosongkan dataset production. Data baru harus lolos validasi model dan smoke test representatif sebelum dianggap siap.

`TOMTOM_TRAFFIC_API_KEY` bersifat opsional dan hanya disimpan di backend. Tanpa key, respons tetap tersedia dengan `trafficSource=historical_profile`; backend tidak menyebut estimasi tersebut sebagai data aktual.

## Public deployment

Production service saat ini berada di FastAPI Cloud. Detail account, application ID, token, database URL, dan konfigurasi environment tidak didokumentasikan secara publik.
