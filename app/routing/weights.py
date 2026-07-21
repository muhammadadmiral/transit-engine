from collections.abc import Callable

from app.models.schema import SearchCriteria, Segment

# Bobot sekunder agar Dijkstra selalu punya tie-break dan tidak memilih
# jalur memutar yang kebetulan sama murah / sama cepat.
# - FARE_EPSILON: Rp1000 ~ 0.001 menit. Durasi tetap dominan untuk fastest.
FARE_EPSILON = 0.000001
FASTEST_TRANSFER_PENALTY_MINUTES = 8.0

# "Termurah" memakai generalized cost: tarif + durasi x nilai waktu.
# Tanpa ini, menghemat Rp3.000 bisa "membenarkan" perjalanan memutar
# berjam-jam (mis. maraton TransJakarta 142 menit vs KRL 50 menit).
# Rp50/menit = Rp3.000/jam: hemat Rp3.000 hanya layak bila memutar
# kurang dari ~1 jam.
CHEAPEST_VALUE_OF_TIME_PER_MINUTE = 50.0


def segment_weight(criteria: SearchCriteria) -> Callable[[Segment], float]:
    if criteria is SearchCriteria.FASTEST:
        return lambda segment: segment.avg_duration_min + float(segment.fare) * FARE_EPSILON
    return lambda segment: float(segment.fare) + duration_cost(segment)


def duration_cost(segment: Segment) -> float:
    """Rupiah-equivalent cost of a segment's travel time for the cheapest
    objective. Also serves as the weight for fare-free continuations of the
    same fare product, so the shortest continuation wins over a detour."""
    return segment.avg_duration_min * CHEAPEST_VALUE_OF_TIME_PER_MINUTE


def transfer_penalty(criteria: SearchCriteria) -> float:
    """Generalized cost of changing vehicles.

    Cheapest converts the same eight-minute inconvenience into rupiah via
    the value of time, so it stays commensurate with fares.
    """
    if criteria is SearchCriteria.FASTEST:
        return FASTEST_TRANSFER_PENALTY_MINUTES
    return FASTEST_TRANSFER_PENALTY_MINUTES * CHEAPEST_VALUE_OF_TIME_PER_MINUTE
