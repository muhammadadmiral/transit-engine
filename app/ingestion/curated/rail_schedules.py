"""Convert official rail timetables into route-level frequency windows."""

import re
from collections import defaultdict
from datetime import date
from io import BytesIO
from statistics import median

from pypdf import PdfReader

from app.models.schema import ServiceFrequency, TransportMode

VERIFIED_AT = date(2026, 7, 22)
KRL_SOURCE_URL = (
    "https://commuterline.id/files/download/documents/"
    "Jadwal%20Commuter%20Line%20Jabodetabek%20-%20Mulai%2013%20Desember%202025.pdf"
)
MRT_SOURCE_URL = "https://jakartamrt.co.id/id/ketentuan-perjalanan"
LRT_JAKARTA_SOURCE_URL = (
    "https://www.lrtjakarta.co.id/"
    "tetap_nyaman_dalam_perjalanan_bersama_lrt_jakarta_selama_ramadan_h_pers466.html"
)
LRT_JABODEBEK_SOURCE_URL = "https://lrtjabodebek.kai.id/jadwal-keberangkatan"

# Consecutive PDF pages belonging to one line and direction. The PDF is parsed,
# rather than transcribed, so updates can be re-imported without code changes.
KRL_PAGE_GROUPS = {
    "krl:bogor-line": ((0, 1), (2, 3)),
    "krl:cikarang-loop-line": ((4, 5), (6, 7)),
    "krl:rangkasbitung-line": ((8,), (9,)),
    "krl:tangerang-line": ((10,), (11,)),
}
ROW_PATTERN = re.compile(r"^\s*\d+\s+(?P<train>\S+)\s+\S+-\S+\s+(?P<body>.*)$")


def build_rail_frequencies(krl_pdf: bytes) -> list[ServiceFrequency]:
    return [*parse_krl_frequencies(krl_pdf), *_fixed_operator_frequencies()]


def parse_krl_frequencies(pdf: bytes) -> list[ServiceFrequency]:
    pages = PdfReader(BytesIO(pdf)).pages
    result: list[ServiceFrequency] = []
    for route_id, direction_groups in KRL_PAGE_GROUPS.items():
        by_day_and_hour: dict[tuple[str, int], list[float]] = defaultdict(list)
        for page_numbers in direction_groups:
            weekday, weekend = _direction_departures(pages, page_numbers)
            for day_type, departures in (("weekday", weekday), ("weekend", weekend)):
                for hour, headway in _hourly_headways(departures).items():
                    by_day_and_hour[(day_type, hour)].append(headway)
        for (day_type, hour), values in sorted(by_day_and_hour.items()):
            result.append(
                _frequency(
                    route_id,
                    TransportMode.KRL,
                    day_type,
                    hour * 60,
                    min(1440, (hour + 1) * 60),
                    round(float(median(values)), 1),
                    KRL_SOURCE_URL,
                )
            )

    # The official PDF places both short Tanjung Priok directions side-by-side.
    result.extend(
        [
            _frequency(
                "krl:tanjung-priok-line",
                TransportMode.KRL,
                day_type,
                300,
                1380,
                30,
                KRL_SOURCE_URL,
            )
            for day_type in ("weekday", "weekend")
        ]
    )
    return result


def _direction_departures(pages, page_numbers: tuple[int, ...]) -> tuple[list[int], list[int]]:
    weekday: list[int] = []
    weekend: list[int] = []
    for page_number in page_numbers:
        text = pages[page_number].extract_text(extraction_mode="layout")
        for line in text.splitlines():
            match = ROW_PATTERN.match(line)
            if match is None:
                continue
            # Search the complete first token; captured groups alone only return hours.
            first_time = re.search(r"\b(?:[01]\d|2[0-3]):[0-5]\d\b", match.group("body"))
            if first_time is None:
                continue
            hour, minute = map(int, first_time.group().split(":"))
            departure = hour * 60 + minute
            weekday.append(departure)
            if not match.group("train").upper().endswith("F"):
                weekend.append(departure)
    return sorted(set(weekday)), sorted(set(weekend))


def _hourly_headways(departures: list[int]) -> dict[int, float]:
    result: dict[int, float] = {}
    for hour in range(24):
        start, end = hour * 60, (hour + 1) * 60
        nearby = [minute for minute in departures if start - 30 <= minute <= end + 30]
        gaps = [
            second - first
            for first, second in zip(nearby, nearby[1:], strict=False)
            if second > first and (start <= first < end or start < second <= end)
        ]
        if gaps:
            result[hour] = min(60.0, max(3.0, float(median(gaps))))
    return result


def _fixed_operator_frequencies() -> list[ServiceFrequency]:
    rows = [
        ("mrt:north-south", TransportMode.MRT, "weekday", 300, 420, 10, MRT_SOURCE_URL),
        ("mrt:north-south", TransportMode.MRT, "weekday", 420, 540, 5, MRT_SOURCE_URL),
        ("mrt:north-south", TransportMode.MRT, "weekday", 540, 1020, 10, MRT_SOURCE_URL),
        ("mrt:north-south", TransportMode.MRT, "weekday", 1020, 1140, 5, MRT_SOURCE_URL),
        ("mrt:north-south", TransportMode.MRT, "weekday", 1140, 1440, 10, MRT_SOURCE_URL),
        ("mrt:north-south", TransportMode.MRT, "weekend", 300, 1440, 10, MRT_SOURCE_URL),
        (
            "lrt-jakarta:line-1",
            TransportMode.LRT,
            "daily",
            330,
            1380,
            10,
            LRT_JAKARTA_SOURCE_URL,
        ),
    ]
    for route_id in ("lrt-jabodebek:bekasi", "lrt-jabodebek:cibubur"):
        rows.extend(
            [
                (
                    route_id,
                    TransportMode.LRT,
                    "weekday",
                    300,
                    540,
                    6,
                    LRT_JABODEBEK_SOURCE_URL,
                ),
                (
                    route_id,
                    TransportMode.LRT,
                    "weekday",
                    540,
                    960,
                    10,
                    LRT_JABODEBEK_SOURCE_URL,
                ),
                (
                    route_id,
                    TransportMode.LRT,
                    "weekday",
                    960,
                    1200,
                    6,
                    LRT_JABODEBEK_SOURCE_URL,
                ),
                (
                    route_id,
                    TransportMode.LRT,
                    "weekday",
                    1200,
                    1410,
                    10,
                    LRT_JABODEBEK_SOURCE_URL,
                ),
                (
                    route_id,
                    TransportMode.LRT,
                    "weekend",
                    300,
                    1410,
                    12.5,
                    LRT_JABODEBEK_SOURCE_URL,
                ),
            ]
        )
    return [_frequency(*row) for row in rows]


def _frequency(
    route_id: str,
    mode: TransportMode,
    day_type: str,
    start_minute: int,
    end_minute: int,
    headway_min: float,
    source_url: str,
) -> ServiceFrequency:
    return ServiceFrequency(
        id=f"{route_id}:{day_type}:{start_minute}",
        route_id=route_id,
        mode=mode,
        day_type=day_type,
        start_minute=start_minute,
        end_minute=end_minute,
        headway_min=headway_min,
        source_url=source_url,
        last_verified_at=VERIFIED_AT,
    )
