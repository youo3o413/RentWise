import math

import httpx

from app.models.schemas import Property
from app.services.map_service import (
    MAP_USER_AGENT,
    _distance_meters,
    _ssl_context,
    find_convenience_stores,
    find_parking_facilities,
    geocode,
    geocode_property_address,
)
from app.services.tdx_service import transit_commutes


VALHALLA_MATRIX_URL = (
    "https://valhalla1.openstreetmap.de/sources_to_targets"
)


def _fallback_commute(
    property_latitude: float,
    property_longitude: float,
    destination_latitude: float,
    destination_longitude: float,
) -> tuple[int, float]:
    direct_km = _distance_meters(
        property_latitude,
        property_longitude,
        destination_latitude,
        destination_longitude,
    ) / 1000
    estimated_route_km = direct_km * 1.25
    minutes = max(1, math.ceil(estimated_route_km / 4.5 * 60))
    return minutes, round(estimated_route_km, 1)


def _matrix_commutes(
    destination: tuple[float, float],
    property_points: list[tuple[str, float, float]],
    costing: str,
) -> dict[str, tuple[int, float]]:
    if not property_points:
        return {}

    destination_latitude, destination_longitude = destination
    response = httpx.post(
        VALHALLA_MATRIX_URL,
        json={
            "sources": [
                {"lat": latitude, "lon": longitude}
                for _, latitude, longitude in property_points
            ],
            "targets": [
                {"lat": destination_latitude, "lon": destination_longitude}
            ],
            "costing": costing,
            "units": "kilometers",
        },
        headers={
            "User-Agent": MAP_USER_AGENT,
            "X-Client-Id": "rentwise-student-demo",
        },
        timeout=20,
        verify=_ssl_context(),
    )
    response.raise_for_status()
    body = response.json()

    results = {}
    matrix = body.get("sources_to_targets", [])
    for index, (property_id, _, _) in enumerate(property_points):
        route = matrix[index][0] if index < len(matrix) and matrix[index] else {}
        duration = route.get("time")
        distance = route.get("distance")
        if duration is None or distance is None or route.get("time") is None:
            continue
        results[property_id] = (
            max(1, math.ceil(float(duration) / 60)),
            round(float(distance), 1),
        )
    return results


def _walking_commutes(
    destination: tuple[float, float],
    property_points: list[tuple[str, float, float]],
) -> dict[str, tuple[int, float]]:
    return _matrix_commutes(destination, property_points, "pedestrian")


def _driving_commutes(
    destination: tuple[float, float],
    property_points: list[tuple[str, float, float]],
) -> dict[str, tuple[int, float]]:
    return _matrix_commutes(destination, property_points, "auto")


def enrich_commute_data(
    properties: list[Property],
    destination: str,
    commute_mode: str = "transit_walk",
    needs_parking: bool = False,
    destination_coordinates: tuple[float, float] | None = None,
) -> list[Property]:
    if destination_coordinates is not None:
        destination_latitude, destination_longitude = destination_coordinates
    else:
        try:
            destination_location = geocode(f"{destination}, 台灣")
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            destination_location = None
        if not destination_location:
            return properties
        destination_latitude, destination_longitude, _ = destination_location
    property_points = []
    point_by_id = {}
    for property_ in properties:
        try:
            point = geocode_property_address(
                id_=property_.id,
                title=property_.title,
                address=property_.address,
                destination=destination,
                source_url=property_.source_url,
            )
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            point = None
        if not point:
            continue
        point_by_id[property_.id] = point
        property_points.append((property_.id, point.latitude, point.longitude))

    try:
        routed = _walking_commutes(
            (destination_latitude, destination_longitude),
            property_points,
        )
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        routed = {}
    try:
        transit_routed = transit_commutes(
            property_points,
            (destination_latitude, destination_longitude),
        )
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        transit_routed = {}
    try:
        driving_routed = _driving_commutes(
            (destination_latitude, destination_longitude),
            property_points,
        )
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        driving_routed = {}
    try:
        stores = find_convenience_stores(list(point_by_id.values()))
        store_lookup_completed = True
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        stores = []
        store_lookup_completed = False
    if commute_mode == "drive" or needs_parking:
        try:
            parking_facilities = find_parking_facilities(
                list(point_by_id.values())
            )
            parking_lookup_completed = True
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            parking_facilities = []
            parking_lookup_completed = False
    else:
        parking_facilities = []
        parking_lookup_completed = False

    enriched = []
    for property_ in properties:
        point = point_by_id.get(property_.id)
        if not point:
            enriched.append(property_)
            continue

        transit_commute = transit_routed.get(property_.id)
        walking_commute = routed.get(property_.id)
        driving_commute = driving_routed.get(property_.id)
        if commute_mode == "drive" and driving_commute:
            minutes, route_distance_km = driving_commute
            transfers = None
            method = "Valhalla 駕車路網"
        elif commute_mode == "drive":
            minutes = None
            route_distance_km = None
            transfers = None
            method = "駕車路線無法取得"
        elif transit_commute:
            minutes, transfers = transit_commute
            route_distance_km = None
            method = "TDX 大眾運輸＋步行"
        elif walking_commute:
            minutes, route_distance_km = walking_commute
            transfers = None
            method = "Valhalla 步行路網"
        else:
            minutes, route_distance_km = _fallback_commute(
                point.latitude,
                point.longitude,
                destination_latitude,
                destination_longitude,
            )
            transfers = None
            method = "地理距離步行推估"

        store_distances = sorted(
            round(
                _distance_meters(
                    point.latitude,
                    point.longitude,
                    store.latitude,
                    store.longitude,
                )
            )
            for store in stores
            if _distance_meters(
                point.latitude,
                point.longitude,
                store.latitude,
                store.longitude,
            ) <= 500
        )
        nearby = list(property_.nearby)
        if store_distances and "便利商店" not in nearby:
            nearby.append("便利商店")
        parking_distances = sorted(
            round(
                _distance_meters(
                    point.latitude,
                    point.longitude,
                    parking.latitude,
                    parking.longitude,
                )
            )
            for parking in parking_facilities
            if _distance_meters(
                point.latitude,
                point.longitude,
                parking.latitude,
                parking.longitude,
            ) <= 500
        )

        enriched.append(
            property_.model_copy(
                update={
                    "commute_minutes": minutes,
                    "distance_reference": f"到 {destination}",
                    "commute_method": method,
                    "commute_transfers": transfers,
                    "route_distance_km": route_distance_km,
                    "transit_commute_minutes": (
                        transit_commute[0] if transit_commute else None
                    ),
                    "walking_commute_minutes": (
                        walking_commute[0] if walking_commute else None
                    ),
                    "walking_distance_km": (
                        walking_commute[1] if walking_commute else None
                    ),
                    "driving_commute_minutes": (
                        driving_commute[0] if driving_commute else None
                    ),
                    "driving_distance_km": (
                        driving_commute[1] if driving_commute else None
                    ),
                    "latitude": point.latitude,
                    "longitude": point.longitude,
                    "nearby": nearby,
                    "nearby_convenience_store_count": (
                        len(store_distances)
                        if store_lookup_completed
                        else property_.nearby_convenience_store_count
                    ),
                    "nearest_convenience_store_meters": (
                        store_distances[0]
                        if store_distances
                        else None
                    ),
                    "nearby_data_source": (
                        "OpenStreetMap"
                        if store_lookup_completed
                        else property_.nearby_data_source
                    ),
                    "nearby_parking_count": (
                        len(parking_distances)
                        if parking_lookup_completed
                        else property_.nearby_parking_count
                    ),
                    "nearest_parking_meters": (
                        parking_distances[0]
                        if parking_distances
                        else None
                    ),
                }
            )
        )
    return enriched
