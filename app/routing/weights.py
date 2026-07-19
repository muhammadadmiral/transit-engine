from collections.abc import Callable

from app.models.schema import SearchCriteria, Segment


def segment_weight(criteria: SearchCriteria) -> Callable[[Segment], float]:
    if criteria is SearchCriteria.FASTEST:
        return lambda segment: segment.avg_duration_min
    return lambda segment: float(segment.fare)

