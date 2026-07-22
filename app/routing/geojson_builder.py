from app.models.schema import FeatureCollection, GeoJsonFeature, Segment


def build_feature_collection(segments: list[Segment]) -> FeatureCollection:
    features = [
        GeoJsonFeature(
            geometry={"type": "LineString", "coordinates": segment.coordinates},
            properties={
                "segmentId": segment.id,
                "routeCode": segment.route_code,
                "routeName": segment.route_name,
                "mode": segment.mode.value,
                "serviceCategory": segment.service_category.value,
                "serviceName": segment.service_name,
                "color": f"#{segment.color}",
                "fromStopId": segment.from_stop_id,
                "toStopId": segment.to_stop_id,
                "avgDurationMin": segment.avg_duration_min,
                "fare": segment.fare,
                "fareProductId": segment.fare_product_id,
                "dataConfidence": segment.data_confidence.value,
                "lastVerifiedAt": segment.last_verified_at.isoformat(),
                "walkingDistanceMeters": segment.walking_distance_meters,
                "walkingRouteSource": (
                    segment.walking_route_source.value if segment.walking_route_source else None
                ),
            },
        )
        for segment in segments
    ]
    return FeatureCollection(features=features)
