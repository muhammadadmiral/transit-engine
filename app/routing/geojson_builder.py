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
                "scheduledWaitMin": segment.scheduled_wait_min,
                "scheduleSourceUrl": segment.schedule_source_url,
                "trafficFactor": segment.traffic_factor,
                "trafficSource": segment.traffic_source.value if segment.traffic_source else None,
                "trafficUpdatedAt": (
                    segment.traffic_updated_at.isoformat() if segment.traffic_updated_at else None
                ),
                "weatherFactor": segment.weather_factor,
                "weatherSource": (segment.weather_source.value if segment.weather_source else None),
                "weatherUpdatedAt": (
                    segment.weather_updated_at.isoformat() if segment.weather_updated_at else None
                ),
                "precipitationMm": segment.precipitation_mm,
                "fare": segment.fare,
                "fareProductId": segment.fare_product_id,
                "dataConfidence": segment.data_confidence.value,
                "lastVerifiedAt": segment.last_verified_at.isoformat(),
                "walkingDistanceMeters": segment.walking_distance_meters,
                "distanceMeters": segment.distance_meters,
                "walkingRouteSource": (
                    segment.walking_route_source.value if segment.walking_route_source else None
                ),
            },
        )
        for segment in segments
    ]
    return FeatureCollection(features=features)
