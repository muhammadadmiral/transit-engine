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
| Geocoding | Nominatim plus Photon | External/community |
| Current road traffic | TomTom Flow Segment Data when configured | External/live |
| Road ETA fallback | Jakarta day/time profile | Estimated |

Official and community corridors are stored in separate namespaces. A failed community refresh never deletes the official layers.

## Angkot model

`flexible_routes` stores a directed `LINESTRING`, route identity, source, confidence, verification date, average speed, and fare product. It does not store invented angkot stops. At graph-build time the corridor is sampled about every 180 metres; coordinate searches project walking access to the nearest usable points. Nearby corridors and fixed rail/bus stops receive short walking connectors.

When OpenStreetMap contains only one non-loop direction for a conventional PP route, the importer adds a clearly named community return direction. Explicitly mapped direction pairs remain untouched.

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
