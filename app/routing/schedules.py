"""Time-aware expected waiting from auditable service-frequency records."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.models.schema import Segment, ServiceFrequency, TransportMode

JAKARTA = ZoneInfo("Asia/Jakarta")


class ServiceFrequencyIndex:
    def __init__(self, frequencies: list[ServiceFrequency]) -> None:
        self._by_route: dict[str, list[ServiceFrequency]] = {}
        for frequency in frequencies:
            self._by_route.setdefault(frequency.route_id, []).append(frequency)

    def expected_wait(
        self, segment: Segment, departure_at: datetime | None
    ) -> tuple[float, str | None]:
        if segment.mode not in {TransportMode.KRL, TransportMode.MRT, TransportMode.LRT}:
            return 0.0, None
        current = departure_at or datetime.now(tz=JAKARTA)
        if current.tzinfo is None:
            current = current.replace(tzinfo=JAKARTA)
        else:
            current = current.astimezone(JAKARTA)
        minute = current.hour * 60 + current.minute
        requested_day = _day_type(current)
        route_frequencies = self._by_route.get(segment.route_id, ())
        candidates = [
            frequency
            for frequency in route_frequencies
            if frequency.day_type in {"daily", requested_day}
            and frequency.start_minute <= minute < frequency.end_minute
        ]
        if candidates:
            frequency = min(candidates, key=lambda item: item.headway_min)
            return round(frequency.headway_min / 2, 1), frequency.source_url
        if not route_frequencies:
            return 0.0, None

        # Outside operating hours, wait until the next scheduled service window.
        for day_offset in range(8):
            service_date = current + timedelta(days=day_offset)
            day_type = _day_type(service_date)
            windows = [
                frequency
                for frequency in route_frequencies
                if frequency.day_type in {"daily", day_type}
                and (day_offset > 0 or frequency.start_minute > minute)
            ]
            if not windows:
                continue
            frequency = min(windows, key=lambda item: item.start_minute)
            wait = day_offset * 1440 + frequency.start_minute - minute
            return round(wait + frequency.headway_min / 2, 1), frequency.source_url
        return 0.0, None


def apply_scheduled_waits(
    segments: list[Segment],
    index: ServiceFrequencyIndex | None,
    departure_at: datetime | None,
) -> list[Segment]:
    if index is None:
        return segments
    elapsed = 0.0
    previous_route: str | None = None
    result: list[Segment] = []
    base = departure_at or datetime.now(tz=JAKARTA)
    base = base.replace(tzinfo=JAKARTA) if base.tzinfo is None else base.astimezone(JAKARTA)
    for segment in segments:
        wait = 0.0
        source_url = None
        if segment.mode is not TransportMode.WALK and segment.route_id != previous_route:
            when = base.timestamp() + elapsed * 60
            wait, source_url = index.expected_wait(
                segment, datetime.fromtimestamp(when, tz=JAKARTA)
            )
            previous_route = segment.route_id
        result.append(
            segment.model_copy(
                update={"scheduled_wait_min": wait, "schedule_source_url": source_url}
            )
        )
        elapsed += wait + segment.avg_duration_min
    return result


def _day_type(value: datetime) -> str:
    return "weekend" if value.weekday() >= 5 else "weekday"
