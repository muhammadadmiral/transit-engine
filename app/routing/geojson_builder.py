from app.models.schema import FeatureCollection, GeoJsonFeature, Segment


def build_feature_collection(segments: list[Segment]) -> FeatureCollection:
    features = [
        GeoJsonFeature(
            geometry={"type": "LineString", "coordinates": segment.coordinates},
            properties={
                "segmentId": segment.id,
                "mode": segment.mode.value,
                "color": f"#{segment.color}",
                "fromStopId": segment.from_stop_id,
                "toStopId": segment.to_stop_id,
                "avgDurationMin": segment.avg_duration_min,
                "fare": segment.fare,
                "dataConfidence": segment.data_confidence.value,
                "lastVerifiedAt": segment.last_verified_at.isoformat(),
            },
        )
        for segment in segments
    ]
    return FeatureCollection(features=features)
