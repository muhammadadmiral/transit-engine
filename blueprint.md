# TransHub Jabodetabek — Product Blueprint

Status: living product document

## 1. Product vision

Informasi transportasi Jabodetabek tersebar di banyak operator. Pengguna yang belum mengenal jaringan biasanya tidak bertanya “jadwal moda ini apa?”, tetapi “dari sini ke sana paling cepat atau paling murah naik apa, dan pindah di mana?”

TransHub menjawab pertanyaan itu sebagai satu perjalanan multimoda. Hasilnya bukan sekadar daftar kendaraan: pengguna mendapat urutan perjalanan, titik pindah, estimasi waktu, transparansi tarif, dan jalur geografis yang mudah diikuti.

## 2. Target users

- Komuter baru yang belum menghafal jaringan dan titik interchange.
- Pendatang atau wisatawan domestik yang membutuhkan instruksi sederhana.
- Komuter reguler yang ingin membandingkan alternatif waktu dan biaya.

## 3. Product principles

### Make the trade-off visible

“Tercepat” dan “termurah” dihitung sebagai dua objective terpisah. Produk tidak menyembunyikan trade-off dalam satu skor “terbaik” yang sulit dijelaskan.

### Be honest about uncertainty

Tarif exact, estimated, range, dan unknown memiliki arti visual yang berbeda. Data community tidak boleh terlihat seolah-olah berasal dari operator resmi. Angkot boleh parsial; klaim coverage tidak boleh melebihi data.

### Explain the transfer

Nilai utama TransHub ada pada momen perpindahan. UI harus membuat lokasi turun, berjalan, dan naik berikutnya lebih jelas daripada sekadar menampilkan polyline panjang.

### The map supports the instruction

Peta bukan dekorasi dan bukan pengganti itinerary. Pengguna harus tetap memahami perjalanan dari daftar langkah, sedangkan peta membantu orientasi spasial.

## 4. Signature experience: Living Route Line

Setelah pencarian selesai, jalur digambar secara berurutan mengikuti perjalanan. Segmen aktif mendapat penekanan, kamera mengikuti area relevan, dan titik transit diberi marker yang jelas. Warna jalur mengikuti identitas layanan, bukan warna brand aplikasi.

Animasi harus memperkuat pemahaman:

1. tampilkan overview seluruh perjalanan;
2. fokus ke segmen pertama;
3. hidupkan jalur sesuai urutan itinerary;
4. pause singkat di titik transit;
5. lanjut ke segmen berikutnya;
6. selalu sediakan kontrol skip/replay dan hormati `prefers-reduced-motion`.

## 5. MVP experience

Alur utama:

1. pengguna memilih stop asal dan tujuan;
2. pengguna dapat memilih waktu berangkat dan profil pembayaran;
3. sistem menampilkan opsi tercepat dan termurah;
4. setiap opsi menampilkan durasi, harga/rentang harga, jumlah pindah, dan tingkat keyakinan;
5. pengguna membuka detail itinerary dan melihat jalur di peta;
6. walking transfer ditampilkan eksplisit sebagai langkah, bukan disembunyikan.

MVP menerima stop ID maupun koordinat pin. Untuk koordinat, backend membandingkan beberapa stop yang directionally usable secara end-to-end, lalu memasukkan connector jalan kaki first/last-mile ke durasi, itinerary, dan GeoJSON. Connector masih berupa garis akses estimasi; pedestrian turn-by-turn tetap fase lanjutan.

## 6. Supported network

| Moda | Peran di produk | Data trust |
| --- | --- | --- |
| KRL | tulang punggung regional | official/curated |
| MRT Jakarta | rapid transit koridor utama | official/curated |
| LRT Jakarta | urban rail | official/curated |
| LRT Jabodebek | koneksi Jakarta–Bekasi–Cibubur | official/curated |
| TransJakarta | main, feeder, microtrans, regional, premium, tourist | official GTFS |
| Angkot | last-mile/feeder yang coverage-nya parsial | community |
| Bikun UI | campus shuttle dan koneksi Stasiun UI | community |

Tidak semua layanan berlabel “TransJakarta” adalah koridor utama. `serviceCategory` menentukan apakah sebuah segmen `main`, `feeder`, `microtrans`, `regional`, `premium`, `tourist`, atau kategori lain.

## 7. Fare philosophy

Fare engine menghitung satu perjalanan lengkap, bukan menjumlahkan angka mentah pada setiap edge.

- TransJakarta dan LRT Jakarta: flat per ride/product.
- MRT Jakarta: matriks origin–destination.
- KRL: band jarak.
- LRT Jabodebek: jarak dengan cap yang bergantung waktu.
- Angkot: estimated range karena tarif lapangan tidak seragam.
- Walking transfer dan Bikun: gratis.
- Profil JakLingko terintegrasi adalah asumsi pembayaran eksplisit, bukan default tersembunyi.

Frontend wajib memakai `fareQuote` sebagai sumber presentasi tarif. `segment.fare` tersedia untuk compatibility dan breakdown, tetapi bukan total journey yang authoritative.

## 8. Service architecture

TransHub memakai dua service dengan batas yang tegas:

| Web application | Transit Engine |
| --- | --- |
| UI, interaction, map, client state | ingestion, database, graph, routing, fare, GeoJSON |
| Tidak mengakses database transit | Satu-satunya pemilik Supabase/PostGIS |
| Mengonsumsi REST/OpenAPI | Menerbitkan kontrak Pydantic/OpenAPI |

Backend membangun directed graph dari segmen transit dan walking transfer. Pathfinder menjalankan objective fastest dan cheapest secara terpisah dengan batas jumlah transfer. Response sudah membawa itinerary dan GeoJSON sehingga frontend tidak merakit graph atau geometri sendiri.

## 9. Data quality policy

Setiap segmen memiliki:

- `dataConfidence`: `official` atau `community`;
- `lastVerifiedAt`: tanggal snapshot diverifikasi;
- `serviceCategory`: peran layanan;
- `fareProductId`: aturan tarif yang digunakan.

Data OSM disaring agar generic bus tidak salah diklasifikasikan sebagai angkot. Proximity walking transfer tidak dibuat antar-stop dengan mode yang sama. Rail–TransJakarta memakai konektor yang ditinjau atau name matching yang dibatasi jarak.

## 10. Non-goals for MVP

- Posisi kendaraan dan gangguan layanan real-time.
- Jadwal keberangkatan presisi per trip.
- Pedestrian turn-by-turn dan akses dari pin di luar radius coverage transit.
- Akun pengguna, favorit tersinkron, atau riwayat server-side.
- Klaim coverage seluruh angkot Jabodetabek.
- Turn-by-turn pedestrian navigation.

## 11. Roadmap

### Phase 1 — reliable multimodal MVP

- Stabilkan kontrak route search dan frontend journey cards.
- Audit representative route lintas semua rail dan TransJakarta.
- Tampilkan fare uncertainty dan data confidence dengan benar.
- Bangun Living Route Line yang aksesibel.

### Phase 2 — better discovery and last mile

- Tingkatkan geocoding/reverse-geocoding dan geometri pedestrian first/last-mile.
- Perluasan angkot berdasarkan koridor prioritas.
- Kanal pelaporan koreksi data.
- Snapshot/version metadata di API.

### Phase 3 — operational intelligence

- Jadwal dan service calendar.
- Data gangguan/realtime jika tersedia resmi.
- Estimasi waktu yang peka jam sibuk.
- Observability, rate limiting, dan cache terdistribusi sesuai kebutuhan traffic.

## 12. Success criteria

MVP dianggap berhasil bila pengguna dapat:

- menemukan asal/tujuan tanpa memahami kode internal jaringan;
- membedakan opsi tercepat dan termurah dalam sekali lihat;
- mengetahui moda, arah, dan lokasi setiap perpindahan;
- memahami mana harga pasti dan mana estimasi;
- mengikuti jalur di peta tanpa kehilangan itinerary tertulis;
- melihat keterbatasan data community secara jujur.
