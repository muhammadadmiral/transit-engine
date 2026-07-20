# TransHub Frontend Integration & Design Guide

Dokumen ini adalah handoff implementasi untuk frontend TransHub. Kontrak aktual tetap berasal dari OpenAPI Transit Engine; guide ini menjelaskan cara mengonsumsinya dan bagaimana hasil routing diharapkan tampil.

## 1. Connection

Production base URL:

```text
https://transit-engine.fastapicloud.dev
```

Simpan sebagai server/public environment variable sesuai kebutuhan framework, misalnya `NEXT_PUBLIC_TRANSIT_API_URL`. Jangan menaruh database URL atau data-refresh secret di frontend.

Kontrak tersedia di:

```text
GET /openapi.json
GET /docs
```

Generate type TypeScript dari OpenAPI agar frontend tidak mendefinisikan ulang response secara manual:

```bash
npx openapi-typescript \
  https://transit-engine.fastapicloud.dev/openapi.json \
  -o src/types/transit-api.d.ts
```

## 2. Core flow

```text
Autocomplete origin/destination
        ↓
POST /route-search
        ↓
Fastest + cheapest options
        ↓
Journey cards + itinerary + GeoJSON map
```

Saat ini route engine menerima **stop ID**, bukan koordinat atau alamat bebas. Nilai `originStopId` dan `destinationStopId` harus berasal dari endpoint stop, bukan dibuat dari nama display.

## 3. Stop autocomplete

Gunakan endpoint ringan ini untuk input asal dan tujuan:

```http
GET /stops?q=dukuh%20atas&limit=20
```

Minimal query dua karakter, limit 1–50. Debounce input sekitar 250–350 ms, batalkan request lama dengan `AbortController`, dan jangan fetch saat query terlalu pendek.

```ts
type TransitStop = {
  id: string;
  name: string;
  lat: number;
  lng: number;
  modes: TransitMode[];
};

export async function searchStops(query: string, signal?: AbortSignal) {
  if (query.trim().length < 2) return [];

  const url = new URL("/stops", process.env.NEXT_PUBLIC_TRANSIT_API_URL);
  url.searchParams.set("q", query.trim());
  url.searchParams.set("limit", "20");

  const response = await fetch(url, { signal });
  if (!response.ok) throw new Error(`Stop search failed: ${response.status}`);
  return (await response.json()) as TransitStop[];
}
```

Tampilkan nama stop, badge moda, dan area/konteks jika nanti tersedia. Simpan object pilihan atau minimal ID + label; jangan mengandalkan teks input sebagai identitas.

## 4. Route search

```http
POST /route-search
Content-Type: application/json
```

```json
{
  "originStopId": "mrt:lebak-bulus",
  "destinationStopId": "lrt-jabodebek:jatimulya",
  "maxTransfers": 3,
  "departureAt": "2026-07-20T07:00:00+07:00",
  "paymentProfile": "standard"
}
```

- `maxTransfers`: 0–5, default 3.
- `departureAt`: opsional, kirim ISO 8601 dengan timezone. Penting untuk LRT Jabodebek.
- `paymentProfile`: `standard` atau `jaklingko_integrated`.

```ts
type RouteSearchInput = {
  originStopId: string;
  destinationStopId: string;
  maxTransfers?: number;
  departureAt?: string;
  paymentProfile?: "standard" | "jaklingko_integrated";
};

export async function searchRoutes(input: RouteSearchInput, signal?: AbortSignal) {
  const response = await fetch(
    new URL("/route-search", process.env.NEXT_PUBLIC_TRANSIT_API_URL),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
      signal,
    },
  );

  if (response.status === 404) return { kind: "not-found" as const };
  if (!response.ok) throw new Error(`Route search failed: ${response.status}`);
  return { kind: "success" as const, data: await response.json() };
}
```

Response selalu mencoba menghasilkan dua option:

- `criteria: "fastest"`
- `criteria: "cheapest"`

Keduanya dapat berisi perjalanan yang sama. Jika signature segmennya identik, UI boleh menampilkan satu card dengan dua badge (“Tercepat & Termurah”), tetapi jangan membuang salah satu hanya karena durasi atau harga kebetulan sama.

## 5. Reading a route option

Field penting:

| Field | Pemakaian frontend |
| --- | --- |
| `criteria` | label Tercepat/Termurah |
| `totalDurationMin` | headline durasi |
| `fareQuote` | satu-satunya sumber display total tarif |
| `transferCount` | jumlah perpindahan kendaraan |
| `segments` | itinerary berurutan |
| `geojson` | layer MapLibre untuk option tersebut |

`totalFare` dipertahankan untuk compatibility/ranking. Untuk UI gunakan `fareQuote`, karena ia membawa status, rentang, komponen, asumsi, dan profil pembayaran.

### Fare display rules

| `fareQuote.status` | Tampilan |
| --- | --- |
| `exact` | `Rp3.500` |
| `estimated` | `± Rp5.000` atau `Estimasi Rp5.000` |
| `range` | `Rp4.000–Rp7.000` |
| `unknown` | `Tarif belum tersedia` |

Gunakan `Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 0 })`. Jangan mengubah `range` menjadi satu angka besar di card. Breakdown dapat memakai `fareQuote.components`; tampilkan `assumptions` sebagai catatan, khususnya profil integrasi.

### Confidence display rules

- `official`: tidak harus mendapat badge besar; dapat tampil sebagai tooltip/source detail.
- `community`: tampilkan badge “Data komunitas” dan tanggal `lastVerifiedAt`.
- Jika satu journey mengandung minimal satu segmen community, card journey harus mempunyai indikator community.

## 6. Building the itinerary

`segments` sudah berurutan. Kelompokkan segmen transit bersebelahan bila `fareProductId`, `routeId`, dan moda menunjukkan ride yang sama. Jangan gabungkan melewati segmen `walk`.

Setiap step minimal menampilkan:

- icon dan nama moda;
- `serviceName` sebagai nama rute/layanan;
- kategori layanan untuk konteks feeder/main/microtrans;
- stop awal dan akhir dari ID yang cocok dengan data stop;
- estimasi durasi;
- badge confidence bila community.

Walking transfer harus menjadi step eksplisit: “Jalan kaki ke …”, durasi, dan garis putus-putus di peta. `transferCount` adalah perpindahan kendaraan, bukan jumlah walking segment.

### Mode values

```ts
type TransitMode =
  | "krl"
  | "mrt"
  | "lrt"
  | "transjakarta"
  | "angkot"
  | "bikun"
  | "walk";
```

LRT Jakarta dan LRT Jabodebek sama-sama `mode: "lrt"`; bedakan lewat `routeId`, `fareProductId`, dan `serviceName`.

### Service category values

```text
main, feeder, microtrans, regional, premium,
shuttle, tourist, transfer, bikun
```

Kategori adalah properti layanan, bukan moda baru. Contoh: TransJakarta feeder tetap memiliki `mode: "transjakarta"`.

## 7. Map rendering

`option.geojson` adalah GeoJSON `FeatureCollection` dengan `LineString`. Koordinat mengikuti standar GeoJSON: `[longitude, latitude]`.

Setiap feature membawa properties seperti:

- `segmentId`
- `mode`
- `serviceCategory`
- `serviceName`
- `color` dalam bentuk `#RRGGBB`
- `fromStopId` / `toStopId`
- `avgDurationMin`
- `fareProductId`
- `dataConfidence`
- `lastVerifiedAt`

Rekomendasi layer MapLibre:

- satu source untuk option aktif;
- layer transit solid memakai `properties.color`;
- walking layer abu-abu dan dashed;
- casing tipis agar rute terbaca di atas basemap;
- marker origin, destination, dan setiap batas transit;
- `fitBounds` seluruh option saat card dipilih;
- jangan load semua 400+ rute saat halaman awal bila tidak dibutuhkan.

Endpoint eksplorasi jaringan tersedia untuk halaman map/network:

```text
GET /network/stops?mode=krl&limit=100&offset=0
GET /network/routes?mode=mrt&limit=100&offset=0
GET /network/routes/{routeId}/geometry
```

Response list memakai `items`, `total`, `limit`, dan `offset`. Selalu paginasi; maksimum 500 per request.

## 8. Design direction

Arah visual mengambil bahasa sistem transit: route diagram, platform signage, wayfinding arrow, dan travel card. Hindari UI dashboard admin atau peta dengan panel generik yang terlalu padat.

### Search state

- Hero berfokus pada input A → B.
- Origin dan destination terasa seperti dua node dalam satu jalur vertikal.
- Swap action mudah ditemukan tetapi tidak lebih dominan dari CTA pencarian.
- Loading menampilkan proses “Menyusun perjalanan”, bukan spinner tanpa konteks.

### Results state

- Card Tercepat dan Termurah menjadi keputusan utama di atas fold.
- Durasi dan tarif menjadi dua angka paling mudah dibandingkan.
- Moda ditampilkan sebagai urutan chip/icon, bukan daftar text panjang.
- Highlight “hemat X menit” atau “hemat RpX” hanya jika dihitung dari dua option nyata.
- Uncertainty tampil dekat harga/data terkait, bukan disembunyikan di footer.

### Itinerary state

- Gunakan garis vertikal yang menghubungkan stop dan transfer.
- Ride step memakai warna operator/rute; walking step netral.
- Titik transit memiliki visual break dan instruksi yang lebih kuat.
- Detail sumber, confidence, dan asumsi tarif berada di disclosure yang tetap mudah ditemukan.

### Living Route Line

Urutan yang diharapkan:

1. route option dipilih dan peta menampilkan overview;
2. polyline digambar dari origin mengikuti urutan segment;
3. itinerary step aktif ikut disorot;
4. kamera bergerak lembut ke area segment aktif;
5. transfer marker pulse satu kali saat perpindahan;
6. destination mendapat completion state.

Gunakan satu orchestration timeline. Jangan menjalankan GSAP dan Framer Motion pada properti DOM yang sama. Untuk `prefers-reduced-motion`, tampilkan seluruh jalur langsung dan ganti perpindahan kamera dengan fit bounds sederhana.

## 9. States and errors

Frontend harus membedakan:

- belum memilih origin/destination;
- sedang autocomplete;
- sedang mencari rute;
- route tidak ditemukan (`404`);
- input tidak valid (`422`);
- backend/database sementara tidak tersedia (`503`);
- network timeout/offline;
- success tetapi fastest dan cheapest identik.

Sediakan retry untuk error sementara. Jangan retry otomatis tanpa batas pada `404` atau `422`. Timeout 20–30 detik masuk akal untuk cold start; tampilkan progress copy yang jujur.

## 10. Caching and client state

- TanStack Query cocok untuk stop search, network list, dan route search.
- Cache autocomplete singkat berdasarkan query normalized.
- Route query key harus memuat origin, destination, max transfer, departure time, dan payment profile.
- Simpan pilihan UI di Zustand/local state; response server tetap di query cache.
- Jangan persist response rute terlalu lama karena dataset backend dapat diperbarui.

## 11. Accessibility checklist

- Semua kontrol dapat dipakai keyboard.
- Combobox autocomplete mengikuti pola ARIA yang benar.
- Warna moda tidak menjadi satu-satunya pembeda; selalu sertakan label/icon.
- Perubahan hasil diumumkan melalui live region yang tidak mengganggu.
- Map mempunyai itinerary text yang setara, bukan satu-satunya sumber informasi.
- Focus berpindah ke heading hasil setelah pencarian sukses.
- Animasi dapat dikurangi dan tidak memicu motion sickness.

## 12. Frontend acceptance checklist

- Types digenerate dari `/openapi.json`.
- Stop ID, bukan nama, dikirim ke route search.
- Fastest dan cheapest dibandingkan secara benar.
- `fareQuote.status` menentukan format harga.
- Community confidence terlihat pada angkot/Bikun.
- Walking transfer terlihat di itinerary dan peta.
- GeoJSON dibaca sebagai longitude–latitude.
- LRT Jakarta dan LRT Jabodebek tidak disatukan berdasarkan `mode` saja.
- Empty, loading, error, identical-options, dan reduced-motion state sudah diuji.
- Tidak ada credential database atau refresh secret di client bundle.
