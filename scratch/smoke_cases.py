"""Smoke-test live route search across many plausible Jabodetabek pairs.

Coordinates come from common land marks. Pair selection aims to cover
cross-corridor usage: KRL Bogor Line, KRL Bekasi Line, KRL Tangerang Line,
MRT, LRT, angkot, Mikrotrans, and combinations of these.
"""
import asyncio
import os
import time
from typing import NamedTuple

from dotenv import load_dotenv

load_dotenv("/Users/admiral/Projects/transhub/transit-engine/.env")
os.environ.setdefault("APP_ENV", "development")

from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.main import app  # noqa: E402


class Case(NamedTuple):
    label: str
    origin: dict  # {"stop_id": "..."} or {"lat": ..., "lng": ...}
    destination: dict


# Pusat kota (landmark) umum dengan halte/stasiun yang sudah dikenal.
CASES: list[Case] = [
    # ------- Bogor -> Depok corridor (KRL)
    Case("Bogor -> Bojong Gede", {"stop_id": "krl:bogor"}, {"stop_id": "krl:bojonggede"}),
    Case("Bogor -> Depok", {"stop_id": "krl:bogor"}, {"stop_id": "krl:depok"}),
    Case("Bogor -> Depok Baru", {"stop_id": "krl:bogor"}, {"stop_id": "krl:depok-baru"}),
    Case("Bogor -> Jakarta Kota", {"stop_id": "krl:bogor"}, {"stop_id": "krl:jakarta-kota"}),
    Case("Cilebut -> Bojong Gede", {"stop_id": "krl:cilebut"}, {"stop_id": "krl:bojonggede"}),
    Case("Depok -> Cibinong", {"stop_id": "krl:depok"}, {"stop_id": "krl:cibinong"}),
    Case("Citayam -> Depok", {"stop_id": "krl:citayam"}, {"stop_id": "krl:depok"}),
    # ------- Cimanggis/Deps areas -> Bintaro (South Tangerang)
    # Cimanggis area
    Case("Cimanggis (Cisalak) -> Bintaro Xchange",
         {"lat": -6.372, "lng": 106.857}, {"lat": -6.272, "lng": 106.728}),
    Case("Cibubur -> Bintaro Xchange",
         {"lat": -6.367, "lng": 106.876}, {"lat": -6.272, "lng": 106.728}),
    Case("Pondok Cabe -> Lebak Bulus", {"stop_id": "krl:pondok-cina"}, {"stop_id": "mrt:lebak-bulus"}),
    Case("Pondok Indah -> Lebak Bulus", {"lat": -6.265, "lng": 106.781}, {"stop_id": "mrt:lebak-bulus"}),
    # ------- Bekasi Line
    Case("Bekasi -> Jakarta Kota", {"stop_id": "krl:bekasi"}, {"stop_id": "krl:jakarta-kota"}),
    Case("Bekasi -> Manggarai", {"stop_id": "krl:bekasi"}, {"stop_id": "krl:manggarai"}),
    Case("Cikarang -> Manggarai", {"stop_id": "krl:cikarang"}, {"stop_id": "krl:manggarai"}),
    Case("Tambun -> Jakarta Kota", {"stop_id": "krl:tambun"}, {"stop_id": "krl:jakarta-kota"}),
    Case("Jatinegara -> Pasar Senen", {"stop_id": "krl:jatinegara"}, {"stop_id": "krl:pasar-senen"}),
    Case("Bekasi -> Tangerang (lintas)", {"stop_id": "krl:bekasi"}, {"stop_id": "krl:tangerang"}),
    # ------- Tangerang Line
    Case("Tangerang -> Duri", {"stop_id": "krl:tangerang"}, {"stop_id": "krl:duri"}),
    Case("Tangerang -> Tanah Abang", {"stop_id": "krl:tangerang"}, {"stop_id": "krl:tanah-abang"}),
    Case("Tanah Tinggi -> Sudirman", {"stop_id": "krl:tanah-tinggi"}, {"stop_id": "krl:sudirman"}),
    Case("Rawa Buntu -> Tanah Abang", {"stop_id": "krl:rawa-buntu"}, {"stop_id": "krl:tanah-abang"}),
    Case("Sudimara -> Duri", {"stop_id": "krl:sudimara"}, {"stop_id": "krl:duri"}),
    Case("Serpong -> Duri", {"stop_id": "krl:serpong"}, {"stop_id": "krl:duri"}),
    # ------- MRT (Lebak Bulus - HI)
    Case("Lebak Bulus -> Dukuh Atas", {"stop_id": "mrt:lebak-bulus"}, {"stop_id": "mrt:dukuh-atas"}),
    Case("Fatmawati -> Blok M", {"stop_id": "mrt:fatmawati"}, {"stop_id": "mrt:blok-m"}),
    Case("Blok M -> Setiabudi", {"stop_id": "mrt:blok-m"}, {"stop_id": "mrt:setiabudi"}),
    # ------- LRT
    Case("Cibubur -> Dukuh Atas (LRT)", {"lat": -6.367, "lng": 106.876},
         {"stop_id": "lrt:dukuh-atas"}),
    # ------- Cross-corridor
    Case("Bekasi -> Lebak Bulus", {"stop_id": "krl:bekasi"}, {"stop_id": "mrt:lebak-bulus"}),
    Case("Bekasi -> Blok M", {"stop_id": "krl:bekasi"}, {"stop_id": "mrt:blok-m"}),
    Case("Tangerang -> Blok M", {"stop_id": "krl:tangerang"}, {"stop_id": "mrt:blok-m"}),
    Case("Bogor -> Blok M", {"stop_id": "krl:bogor"}, {"stop_id": "mrt:blok-m"}),
    # ------- Dengan angkot (kandidat Mikrotrans)
    Case("Stasiun UI -> Terminal Depok", {"stop_id": "krl:universitas-indonesia"},
         {"stop_id": "transjakarta:B05702P"}),
    Case("Depok Baru -> Terminal Depok",
         {"stop_id": "krl:depok-baru"}, {"stop_id": "transjakarta:B05702P"}),
]


def build_payload(case: Case) -> tuple[str, dict]:
    payload: dict = {"maxTransfers": 4, "paymentProfile": "standard"}
    if "stop_id" in case.origin:
        payload["originStopId"] = case.origin["stop_id"]
    elif "lat" in case.origin:
        payload["originLat"] = case.origin["lat"]
        payload["originLng"] = case.origin["lng"]
    if "stop_id" in case.destination:
        payload["destinationStopId"] = case.destination["stop_id"]
    elif "lat" in case.destination:
        payload["destinationLat"] = case.destination["lat"]
        payload["destinationLng"] = case.destination["lng"]
    return case.label, payload


async def run_one(client: AsyncClient, case: Case, verbose: bool = False) -> dict:
    label, payload = build_payload(case)
    started = time.perf_counter()
    response = await client.post("/route-search", json=payload)
    elapsed_ms = (time.perf_counter() - started) * 1000
    summary = {"label": label, "status": response.status_code, "ms": elapsed_ms}
    if response.status_code != 200:
        summary["error"] = response.json()
        return summary
    body = response.json()
    options = body["options"]
    summary["options"] = [
        {
            "criteria": opt["criteria"],
            "duration": round(opt["totalDurationMin"]),
            "fare": opt["totalFare"],
            "transfers": opt["transferCount"],
            "hops": sum(1 for s in opt["segments"] if s["mode"] != "walk"),
            "modes": "+".join({s["mode"] for s in opt["segments"]}),
            "verbose": opt["segments"] if verbose else None,
        }
        for opt in options
    ]
    return summary


async def main() -> None:
    import sys
    if "--inprocess" in sys.argv:
        base_url = "http://test"
    else:
        base_url = os.environ.get("TRANSHUB_API", "http://localhost:7860")
    results = []
    async with AsyncClient(base_url=base_url, timeout=180.0) as client:
        for case in CASES:
            try:
                results.append(await run_one(client, case))
            except Exception as exc:  # noqa: BLE001
                results.append({"label": case.label, "status": "err", "ms": 0, "error": str(exc)})
    for r in results:
        same = (len(r.get("options", [])) > 1
                and r["options"][0] == r["options"][1])
        print(f"\n### {r['label']}  HTTP {r['status']}  ({r['ms']:.0f} ms)"
              f"{'  [sama]' if same else ''}")
        if "error" in r:
            print(f"   ERROR: {r['error']}")
            continue
        for opt in r["options"]:
            print(f"   [{opt['criteria']:<8}] {opt['duration']:>4} mnt · Rp{opt['fare']:<6} "
                  f"{opt['transfers']} transit · {opt['hops']} hops · {opt['modes']}")
            if opt.get("verbose"):
                for s in opt["verbose"]:
                    print(f"       [{s['mode']:<14}] {s['routeCode'] or '-':<10} {s['avgDurationMin']:>5.1f}m "
                          f"{s['fromStopId']} -> {s['toStopId']}")


asyncio.run(main())
