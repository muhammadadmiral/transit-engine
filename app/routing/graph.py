import networkx as nx

from app.models.schema import Segment


def build_graph(segments: list[Segment]) -> nx.MultiDiGraph:
    graph = nx.MultiDiGraph()
    for segment in segments:
        first, last = segment.coordinates[0], segment.coordinates[-1]
        is_flexible = segment.from_stop_id.startswith("flex:")
        graph.add_node(
            segment.from_stop_id,
            lat=segment.from_stop_lat if segment.from_stop_lat is not None else first[1],
            lng=segment.from_stop_lng if segment.from_stop_lng is not None else first[0],
            name=segment.from_stop_name,
            flexible=is_flexible,
            flexible_route_id=segment.route_id if is_flexible else None,
        )
        is_flexible = segment.to_stop_id.startswith("flex:")
        graph.add_node(
            segment.to_stop_id,
            lat=segment.to_stop_lat if segment.to_stop_lat is not None else last[1],
            lng=segment.to_stop_lng if segment.to_stop_lng is not None else last[0],
            name=segment.to_stop_name,
            flexible=is_flexible,
            flexible_route_id=segment.route_id if is_flexible else None,
        )
        graph.add_edge(segment.from_stop_id, segment.to_stop_id, key=segment.id, segment=segment)
    return graph
