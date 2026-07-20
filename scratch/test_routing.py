import asyncio
from app.db.session import SessionLocal
from app.db.transit_repository import load_segments, search_stops
from app.routing.graph import build_graph
from app.routing.pathfinder import find_route
from app.models.schema import SearchCriteria

async def main():
    async with SessionLocal() as session:
        segments = await load_segments(session)
        graph = build_graph(segments)
        
        stops_dpb = await search_stops(session, "Depok Baru", 5)
        origin = stops_dpb[0].id
        
        # Pick angkot stops
        angkot_stops = [node for node in graph.nodes if str(node).startswith("angkot:") and "bikun" not in str(node)]
        
        import random
        for _ in range(50):
            dest = random.choice(angkot_stops)
            try:
                route = find_route(
                    graph=graph,
                    origin_stop_id=origin,
                    destination_stop_id=dest,
                    criteria=SearchCriteria.FASTEST,
                    max_transfers=4
                )
                print(f"\n--- SUCCESS! Route found from {stops_dpb[0].name} to {dest} ---")
                print(f"Duration: {route.total_duration_min:.1f} min | Fare: Rp {route.total_fare} | Transfers: {route.transfer_count}")
                for seg in route.segments:
                    print(f"  [{seg.mode.upper()}] {seg.service_name}")
                return
            except Exception:
                continue
        print("Could not find a connected route after 50 tries.")

if __name__ == "__main__":
    asyncio.run(main())
