"""Verbose diagnostic for specific cases."""
import asyncio
import json
import os

from dotenv import load_dotenv
from httpx import AsyncClient

load_dotenv("/Users/admiral/Projects/transhub/transit-engine/.env")
os.environ.setdefault("APP_ENV", "development")

CASES = [
    ("Cibubur -> Bintaro", {"originLat": -6.367, "originLng": 106.876,
                            "destinationLat": -6.272, "destinationLng": 106.728,
                            "maxTransfers": 4, "paymentProfile": "standard"}),
    ("Pondok Cabe -> Lebak Bulus", {"originStopId": "krl:pondok-cina",
                                    "destinationStopId": "mrt:lebak-bulus",
                                    "maxTransfers": 4, "paymentProfile": "standard"}),
    ("Bogor -> Blok M", {"originStopId": "krl:bogor", "destinationStopId": "mrt:blok-m",
                         "maxTransfers": 4, "paymentProfile": "standard"}),
    ("Pondok Indah -> Lebak Bulus", {"originLat": -6.265, "originLng": 106.781,
                                     "destinationStopId": "mrt:lebak-bulus",
                                     "maxTransfers": 4, "paymentProfile": "standard"}),
    ("Stasiun UI -> Terminal Depok", {"originStopId": "krl:universitas-indonesia",
                                      "destinationStopId": "transjakarta:B05702P",
                                      "maxTransfers": 4, "paymentProfile": "standard"}),
]


async def main() -> None:
    async with AsyncClient(base_url="http://localhost:7860", timeout=180.0) as client:
        for label, payload in CASES:
            response = await client.post("/route-search", json=payload)
            print(f"\n### {label}")
            if response.status_code != 200:
                print(response.json()); continue
            body = response.json()
            for opt in body["options"]:
                print(f"\n[{opt['criteria']}] {opt['totalDurationMin']:.0f} mnt · Rp{opt['totalFare']} · {opt['transferCount']} transit")
                for s in opt["segments"]:
                    print(f"  {s['mode']:<14} {s['routeCode'] or '-':<10} {s['avgDurationMin']:>5.1f}m Rp{s['fare']:<5} {s['fromStopId']} -> {s['toStopId']}")


asyncio.run(main())
