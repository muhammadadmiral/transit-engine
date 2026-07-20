import asyncio
from app.db.session import SessionLocal
from app.routing.graph_cache import get_routing_graph
from app.routing.pathfinder import find_route
from app.models.schema import SearchCriteria

async def main():
    async with SessionLocal() as session:
        print("Loading graph...")
        graph = await get_routing_graph(session)
        print("Finding route...")
        opt = find_route(
            graph=graph,
            origin_stop_id="krl:bogor",
            destination_stop_id="bikun:fisip",
            criteria=SearchCriteria.FASTEST,
            max_transfers=3,
        )
        print(f"Total: {opt.total_duration_min} min, {opt.transfer_count} transfers")
        for seg in opt.segments:
            print(f"  - {seg.mode.value} from {seg.from_stop_id} to {seg.to_stop_id} ({seg.service_name})")

asyncio.run(main())
