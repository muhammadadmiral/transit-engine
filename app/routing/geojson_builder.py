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
                "gradientStart": _gradient_colors(segment)[0],
                "gradientMid": _gradient_colors(segment)[1],
                "gradientEnd": _gradient_colors(segment)[2],
                "animationDirection": "forward",
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
                "trafficDelayMin": segment.traffic_delay_min,
                "accessAction": (
                    segment.access_action.value if segment.access_action else None
                ),
                "instruction": segment.instruction,
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


def _gradient_colors(segment: Segment) -> tuple[str, str, str]:
    """Return mode-aware colors while retaining the operator's route color."""
    primary = f"#{segment.color.upper()}"
    if segment.mode.value == "krl":
        return "#14213D", primary, "#F8FAFC"
    if segment.mode.value == "bikun":
        return "#FFD43B", primary, "#F59E0B"
    if segment.mode.value == "transjakarta":
        return primary, "#38BDF8", "#E0F2FE"
    if segment.mode.value == "jaklingko":
        return "#0F766E", primary, "#5EEAD4"
    if segment.mode.value == "angkot":
        return "#F59E0B", primary, "#FDE68A"
    if segment.mode.value == "walk":
        return "#64748B", "#CBD5E1", "#64748B"
    return _shade(primary, -0.22), primary, _shade(primary, 0.34)


def _shade(color: str, amount: float) -> str:
    value = color.lstrip("#")
    channels = [int(value[index : index + 2], 16) for index in (0, 2, 4)]
    target = 255 if amount >= 0 else 0
    ratio = abs(amount)
    shaded = [round(channel + (target - channel) * ratio) for channel in channels]
    return "#" + "".join(f"{channel:02X}" for channel in shaded)
