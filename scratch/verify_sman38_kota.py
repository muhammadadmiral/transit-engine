import asyncio
import os
import time

from dotenv import load_dotenv

load_dotenv("/Users/admiral/Projects/transhub/transit-engine/.env")

os.environ.setdefault("APP_ENV", "development")

from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.main import app  # noqa: E402

SMAN38 = {"lat": -6.3406, "lng": 106.8345}


async def search(client: AsyncClient, payload: dict) -> None:
    label = payload.pop("label", "")
    started = time.perf_counter()
    response = await client.post("/route-search", json=payload)
    elapsed = (time.perf_counter() - started) * 1000
    print(f"\n### {label} — HTTP {response.status_code} ({elapsed:.0f} ms)")
    if response.status_code != 200:
        print(response.json())
        return
    body = response.json()
    for option in body["options"]:
        print(f"[{option['criteria']}] {option['totalDurationMin']:.0f} mnt · Rp{option['totalFare']} · {option['transferCount']} transit")
        for seg in option["segments"]:
            print(f"   {seg['mode']:13s} {seg['routeCode'] or '':8s} {seg['avgDurationMin']:5.1f}m Rp{seg['fare']:<6} {seg['fromStopId']} -> {seg['toStopId']}")


async def main() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await search(client, {
            "label": "SMAN 38 (koordinat) -> Stasiun Jakarta Kota",
            "originLat": SMAN38["lat"],
            "originLng": SMAN38["lng"],
            "destinationStopId": "krl:jakarta-kota",
            "maxTransfers": 3,
            "paymentProfile": "standard",
        })
        await search(client, {
            "label": "SMAN 38 (halte TJ B05266P) -> Stasiun Jakarta Kota",
            "originStopId": "transjakarta:B05266P",
            "destinationStopId": "krl:jakarta-kota",
            "maxTransfers": 3,
            "paymentProfile": "standard",
        })


asyncio.run(main())
