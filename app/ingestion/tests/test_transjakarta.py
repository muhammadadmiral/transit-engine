from datetime import date

import pandas as pd

from app.ingestion.gtfs.transjakarta import normalize_feed


def test_normalizes_two_directed_segments_and_keeps_boarding_fare() -> None:
    dataset = normalize_feed(
        stops=pd.DataFrame(
            [
                {"stop_id": "a", "stop_name": "A", "stop_lat": -6.2, "stop_lon": 106.8},
                {"stop_id": "b", "stop_name": "B", "stop_lat": -6.21, "stop_lon": 106.81},
                {"stop_id": "c", "stop_name": "C", "stop_lat": -6.22, "stop_lon": 106.82},
            ]
        ),
        routes=pd.DataFrame([{"route_id": "1", "route_color": "00AA11"}]),
        trips=pd.DataFrame(
            [
                {
                    "trip_id": "trip",
                    "route_id": "1",
                    "direction_id": "0",
                    "shape_id": "shape",
                }
            ]
        ),
        stop_times=pd.DataFrame(
            [
                {
                    "trip_id": "trip",
                    "stop_sequence": 1,
                    "stop_id": "a",
                    "departure_time": "05:00:00",
                    "arrival_time": "05:00:00",
                    "shape_dist_traveled": 0,
                },
                {
                    "trip_id": "trip",
                    "stop_sequence": 2,
                    "stop_id": "b",
                    "departure_time": "05:04:00",
                    "arrival_time": "05:04:00",
                    "shape_dist_traveled": 1000,
                },
                {
                    "trip_id": "trip",
                    "stop_sequence": 3,
                    "stop_id": "c",
                    "departure_time": "05:10:00",
                    "arrival_time": "05:10:00",
                    "shape_dist_traveled": 2000,
                },
            ]
        ),
        shapes=pd.DataFrame(
            [
                {
                    "shape_id": "shape",
                    "shape_pt_sequence": 1,
                    "shape_pt_lat": -6.2,
                    "shape_pt_lon": 106.8,
                    "shape_dist_traveled": 0,
                },
                {
                    "shape_id": "shape",
                    "shape_pt_sequence": 2,
                    "shape_pt_lat": -6.205,
                    "shape_pt_lon": 106.805,
                    "shape_dist_traveled": 500,
                },
                {
                    "shape_id": "shape",
                    "shape_pt_sequence": 3,
                    "shape_pt_lat": -6.21,
                    "shape_pt_lon": 106.81,
                    "shape_dist_traveled": 1000,
                },
            ]
        ),
        fare_attributes=pd.DataFrame([{"fare_id": "regular", "price": "3500"}]),
        fare_rules=pd.DataFrame([{"fare_id": "regular", "route_id": "1"}]),
        verified_at=date(2026, 7, 20),
    )

    assert len(dataset.stops) == 3
    assert [(segment.from_stop_id, segment.to_stop_id) for segment in dataset.segments] == [
        ("transjakarta:a", "transjakarta:b"),
        ("transjakarta:b", "transjakarta:c"),
    ]
    assert {segment.route_id for segment in dataset.segments} == {"transjakarta:1:0"}
    assert [segment.avg_duration_min for segment in dataset.segments] == [4, 6]
    assert {segment.fare for segment in dataset.segments} == {3500}
    assert dataset.segments[0].coordinates == [
        (106.8, -6.2),
        (106.805, -6.205),
        (106.81, -6.21),
    ]
