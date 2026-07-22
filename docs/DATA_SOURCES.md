# Data sources and refresh

The backend is the only owner of geocoding, transit data, schedules, fares, and ETA metadata. The frontend sends coordinates or stop IDs and renders the returned route and GeoJSON.

## Sources

| Layer | Source | Confidence |
| --- | --- | --- |
| TransJakarta and Mikrotrans | Official TransJakarta GTFS | Official |
| KRL schedule | Current KAI Commuter Jabodetabek timetable PDF | Official |
| MRT/LRT frequency | Operator service-hour and headway publications | Official |
| Kabupaten Bogor angkot | Pemkab Bogor `Trayek Angkutan Umum` ArcGIS layer | Official |
| Depok D03/D11 | Depok route regulation and reviewed road geometry | Official route, curated geometry |
| Other conventional angkot | Filtered OpenStreetMap route relations | Community |
| Geocoding | TomTom Search/Reverse when configured, with Nominatim and Photon fallbacks | External/community |
| Current road traffic | TomTom route summary/Flow; optional budgeted Google Routes fallback | External/live |
| Current precipitation | Open-Meteo current conditions | External/live |
| Road map matching | TomTom Snap to Roads, optional reviewed refinement | External |
| Road ETA fallback | Jakarta day/time profile | Estimated |
| Ojek online fallback | Nearest transit connector only; no operator API | Estimated |

Official and community corridors are stored in separate namespaces. A failed community refresh never deletes the official layers.

## Angkot model

`flexible_routes` stores a directed `LINESTRING`, route identity, source, confidence, verification date, average speed, and fare product. It does not store invented angkot stops. At graph-build time the corridor is sampled about every 180 metres; coordinate searches project walking access to the nearest usable points. Nearby corridors and fixed rail/bus stops receive short walking connectors.

When OpenStreetMap contains only one non-loop direction for a conventional PP route, the importer adds a clearly named community return direction. Explicitly mapped direction pairs remain untouched.

## Mikrotrans is not modeled as flexible angkot

Mikrotrans uses small vehicles and serves neighborhood streets, but the official TransJakarta GTFS publishes ordered stop points and trip shapes. The engine therefore keeps it in the compatibility API mode `jaklingko`, labels it **Mikrotrans**, and permits boarding/alighting only at those official points. A point may be a simple signed bus stop rather than a BRT-style shelter. Conventional angkot remains the only hail-and-ride corridor model.

JakLingko is the wider integrated transport/payment system, not the vehicle class. The compatibility mode name is retained so existing clients do not break; `serviceCategory=microtrans` is the precise service classification.

## Optional TomTom enhancement

Set `TOMTOM_API_KEY` only on the backend. The same secret enables POI/address search, reverse geocoding, current road traffic, and the explicit angkot trace-refinement command:

```bash
# Validate provider output without changing the database
.venv/bin/python -m app.ingestion.geometry.refine_angkot_tracks

# Persist only plausible map-matched traces
.venv/bin/python -m app.ingestion.geometry.refine_angkot_tracks --apply
```

The refiner follows the already sourced trace and rejects shifted endpoints or implausible length changes. It does not ask a road router to invent the path between termini. Review provider licensing before persisting production-derived geometry.

Traffic enrichment never replaces a transit track. TomTom receives up to five
anchors sampled from the official GTFS or reviewed angkot geometry and only its
current-versus-historical duration ratio is applied. The GeoJSON remains the
operator/reviewed geometry, so a car route cannot pull a Mikrotrans, TransJakarta,
or angkot line onto a nearby shortcut.

## Optional Google Routes fallback

`GOOGLE_MAPS_API_KEY` enables a backend-only fallback when no TomTom key is
available. Requests ask only for `duration` and `staticDuration`; the returned
Google polyline is deliberately not rendered or persisted. The defaults cap one
process at 100 calls/day and 2,000 calls/month. These counters reset on process
restart, so production must also set a slightly lower hard quota and billing
alert in Google Cloud. `TRAFFIC_AWARE` is a Pro Routes request; do not expose the
key in Vite/client environment variables.

The July 2026 Google Maps price list gives Compute Routes Pro a 5,000-event
monthly free usage cap. Keep the application budget below that cap because other
projects/SKUs on the same billing account and quota-versus-billing reporting lag
can still affect the bill.

## Stasiun UI paid-area crossing

The graph contains a reviewed pedestrian access edge between the campus side and
the Margonda/Jalan Pepaya side of Stasiun UI. It is labeled as a paid station
crossing, retains its peron/gate instruction, uses the minimum KRL fare product,
and is never overwritten by generic pedestrian routing. This lets journeys such
as FT UI → Bikun → Stasiun UI → opposite gate → Jalan Pepaya/Margonda render as
separate, auditable legs.

Short gaps of 350–1,500 metres inside an otherwise sourced trace can be filled
through the configured Valhalla/OSM road network. Larger holes are rejected:

```bash
.venv/bin/python -m app.ingestion.geometry.repair_angkot_gaps
.venv/bin/python -m app.ingestion.geometry.repair_angkot_gaps --apply
```

OSM relation members are reordered only when they form a continuous chain.
Relations with more than five percent disconnected members are quarantined
instead of being rendered as straight lines.

The current curated Depok inbound traces for D03, D11, and D105 are community
reverse-direction approximations. Their remaining sub-1.2 km sparse spans are
not auto-routed because legal car routing produces multi-kilometre one-way
detours that are not evidence of the angkot's licensed inbound streets. Replace
them only with an attributable inbound trace or reviewed field observation.

## Refresh commands

```bash
.venv/bin/alembic upgrade head
.venv/bin/python -m app.ingestion.gtfs.import_transjakarta
.venv/bin/python -m app.ingestion.curated.import_rail_schedules
.venv/bin/python -m app.ingestion.curated.import_angkot
.venv/bin/python -m app.ingestion.official.import_bogor_angkot
.venv/bin/python -m app.ingestion.osm.import_osm
```

Run the official layers before the OSM layer. Imports are namespaced and transactional.

## Known source boundary

No single open, machine-readable authority currently publishes street-level geometry for every conventional angkot in all Jabodetabek municipalities. The engine therefore exposes source and confidence instead of fabricating certainty. Bogor has the strongest official geometry coverage; Bekasi, Tangerang, and some Depok corridors still depend on reviewed OSM relations. Missing tracks should be added only from an attributable route publication or a reviewed field trace.

There is no public Gojek booking/fare API in this project. When no usable transit is found inside the walking radius, the API may offer a generic `ride_hail` connector up to the configured radius. Its time and fare are explicitly estimates; it neither checks vehicle availability nor books a trip.
