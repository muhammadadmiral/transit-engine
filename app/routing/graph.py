import networkx as nx

from app.models.schema import Segment


def build_graph(segments: list[Segment]) -> nx.MultiDiGraph:
    graph = nx.MultiDiGraph()
    for segment in segments:
        graph.add_edge(segment.from_stop_id, segment.to_stop_id, key=segment.id, segment=segment)
    return graph
