import math
import re
import ssl
import threading
import time
from functools import lru_cache
from typing import Any

import certifi
import httpx

from app.models.schemas import (
    MapContextRequest,
    MapContextResponse,
    MapPoint,
    MapPropertyInput,
)
from app.services.rent591_service import REGIONS, resolve_591_location


NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_REVERSE_URL = "https://nominatim.openstreetmap.org/reverse"
OVERPASS_URLS = (
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
)
MAP_USER_AGENT = "RentWise/1.0 (student rental decision platform)"
LOCAL_ADMIN_PATTERN = r"[\u4e00-\u9fff]{1,3}(?:區|鄉|鎮|市)"
_nominatim_lock = threading.Lock()
_last_nominatim_request = 0.0


def _ssl_context() -> ssl.SSLContext:
    context = ssl.create_default_context(cafile=certifi.where())
    if hasattr(ssl, "VERIFY_X509_STRICT"):
        context.verify_flags &= ~ssl.VERIFY_X509_STRICT
    return context


def _region_name(destination: str) -> str:
    explicit_region = re.search(
        r"([\u4e00-\u9fff]{2,3}[縣市])",
        destination.replace("臺", "台"),
    )
    if explicit_region:
        return explicit_region.group(1)
    try:
        region_id = resolve_591_location(destination)["region"]
    except Exception:
        return "台灣"
    return next(
        (
            name.replace("臺", "台")
            for name, value in REGIONS.items()
            if value == region_id
        ),
        "台灣",
    )


def _clean_listing_address(address: str) -> str:
    cleaned = re.sub(r"^無\s+", "", address).strip()
    cleaned = re.sub(r"^(?:地址|位置)\s*[:：]\s*", "", cleaned)
    cleaned = re.sub(
        r"(?:\d+\s*[樓Ff]|[Bb]\d+|地下\d+樓)(?:之\d+)?(?:室)?(?:.*)$",
        "",
        cleaned,
    ).strip()
    cleaned = re.sub(r"\s+", "", cleaned)
    separated = re.search(
        r"(?:[\u4e00-\u9fff]{2,3}[市縣])?"
        rf"(?P<district>{LOCAL_ADMIN_PATTERN})"
        r"\s*[-－—]\s*(?P<street>.+)",
        cleaned,
    )
    if separated:
        return f"{separated.group('street').strip()}, {separated.group('district')}"

    concatenated = re.match(
        r"(?:[\u4e00-\u9fff]{2,3}[市縣])?"
        rf"(?P<district>{LOCAL_ADMIN_PATTERN})"
        r"(?P<street>.+(?:路|街|大道).*)",
        cleaned,
    )
    if concatenated:
        return (
            f"{concatenated.group('street').strip()}, "
            f"{concatenated.group('district')}"
        )
    return cleaned


def _street_level_address(address: str) -> str:
    parts = [part.strip() for part in address.split(",") if part.strip()]
    street = parts[0] if parts else address
    district = (
        parts[1]
        if len(parts) > 1 and re.fullmatch(LOCAL_ADMIN_PATTERN, parts[1])
        else ""
    )
    street = re.sub(
        r"(?:\d+|[XxＸｘ]+|[Ｏ○〇]+)(?:巷|弄|號).*$",
        "",
        street,
    ).strip()
    return f"{street}, {district}" if street and district else street


def _property_geocode_queries(address: str, region_name: str) -> list[str]:
    street_address = _street_level_address(address)
    candidates = [address]
    if street_address and street_address != address:
        candidates.append(street_address)
    queries = []
    for candidate in candidates:
        if not candidate:
            continue
        queries.append(f"{candidate}, {region_name}, 台灣")
        parts = [part.strip() for part in candidate.split(",") if part.strip()]
        street = parts[0]
        district = (
            parts[1]
            if len(parts) > 1
            and re.fullmatch(LOCAL_ADMIN_PATTERN, parts[1])
            else ""
        )
        queries.append(f"{region_name}{district}{street}, 台灣")
    return list(dict.fromkeys(queries))


def _district_from_address(address: str) -> str:
    match = re.search(rf"({LOCAL_ADMIN_PATTERN})", address)
    return match.group(1) if match else ""


def _rate_limited_nominatim_get(
    params: dict[str, str],
    url: str = NOMINATIM_URL,
) -> httpx.Response:
    global _last_nominatim_request
    with _nominatim_lock:
        elapsed = time.monotonic() - _last_nominatim_request
        if elapsed < 1.05:
            time.sleep(1.05 - elapsed)
        response = httpx.get(
            url,
            params=params,
            headers={"User-Agent": MAP_USER_AGENT, "Accept-Language": "zh-TW"},
            timeout=15,
            verify=_ssl_context(),
        )
        _last_nominatim_request = time.monotonic()
        return response


@lru_cache(maxsize=512)
def geocode(query: str) -> tuple[float, float, str] | None:
    response = _rate_limited_nominatim_get(
        {
            "q": query,
            "format": "jsonv2",
            "countrycodes": "tw",
            "limit": "1",
        }
    )
    response.raise_for_status()
    results = response.json()
    if not results:
        return None
    result = results[0]
    return float(result["lat"]), float(result["lon"]), result.get("display_name", query)


@lru_cache(maxsize=512)
def reverse_geocode(latitude: float, longitude: float) -> str | None:
    response = _rate_limited_nominatim_get(
        {
            "lat": str(latitude),
            "lon": str(longitude),
            "format": "jsonv2",
            "zoom": "18",
        },
        NOMINATIM_REVERSE_URL,
    )
    response.raise_for_status()
    result = response.json()
    return result.get("display_name") or None


def _geocode_property(
    property_: MapPropertyInput,
    region_name: str,
    allow_district_fallback: bool = False,
) -> MapPoint | None:
    if property_.latitude is not None and property_.longitude is not None:
        return MapPoint(
            id=property_.id,
            title=property_.title,
            address=property_.address,
            latitude=property_.latitude,
            longitude=property_.longitude,
            kind="property",
            score=property_.score,
            source_url=property_.source_url,
        )
    address = _clean_listing_address(property_.address)
    location = None
    for query in _property_geocode_queries(address, region_name):
        location = geocode(query)
        if location:
            break
    approximate = False
    district = _district_from_address(address)
    if not location and allow_district_fallback and district:
        location = geocode(f"{district}, {region_name}, 台灣")
        approximate = location is not None
    if not location:
        return None
    latitude, longitude, display_name = location
    return MapPoint(
        id=property_.id,
        title=property_.title,
        address=(
            f"{property_.address}（僅定位至{district}代表點）"
            if approximate
            else display_name
        ),
        latitude=latitude,
        longitude=longitude,
        kind="property",
        score=property_.score,
        source_url=property_.source_url,
        is_approximate=approximate,
    )


def geocode_property_address(
    id_: str,
    title: str,
    address: str,
    destination: str,
    score: float = 0,
    source_url: str = "",
    region_name: str = "",
) -> MapPoint | None:
    return _geocode_property(
        MapPropertyInput(
            id=id_,
            title=title,
            address=address,
            score=score,
            source_url=source_url,
        ),
        region_name.strip() or _region_name(destination),
    )


def _distance_meters(
    latitude_a: float,
    longitude_a: float,
    latitude_b: float,
    longitude_b: float,
) -> float:
    radius = 6_371_000
    phi_a, phi_b = math.radians(latitude_a), math.radians(latitude_b)
    delta_phi = math.radians(latitude_b - latitude_a)
    delta_lambda = math.radians(longitude_b - longitude_a)
    value = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi_a) * math.cos(phi_b) * math.sin(delta_lambda / 2) ** 2
    )
    return radius * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))


def _store_address(tags: dict[str, Any]) -> str:
    if tags.get("addr:full"):
        return str(tags["addr:full"])
    return "".join(
        str(tags.get(key, ""))
        for key in ("addr:city", "addr:district", "addr:street", "addr:housenumber")
    ) or "OpenStreetMap 未提供地址"


def _find_osm_amenities(
    points: list[MapPoint],
    amenity_filter: str,
    kind: str,
    default_title: str,
) -> list[MapPoint]:
    if not points:
        return []
    clauses = []
    for point in points:
        clauses.append(
            f'nwr[{amenity_filter}](around:500,'
            f"{point.latitude:.6f},{point.longitude:.6f});"
        )
    query = f'[out:json][timeout:12];({"".join(clauses)});out center tags;'
    response = None
    last_error = None
    for endpoint in OVERPASS_URLS:
        try:
            candidate = httpx.post(
                endpoint,
                data={"data": query},
                headers={"User-Agent": MAP_USER_AGENT, "Accept": "application/json"},
                timeout=15,
                verify=_ssl_context(),
            )
            candidate.raise_for_status()
            response = candidate
            break
        except httpx.HTTPError as exc:
            last_error = exc
    if response is None:
        raise last_error or httpx.HTTPError("No Overpass endpoint is available")

    amenities = []
    seen = set()
    for element in response.json().get("elements", []):
        latitude = element.get("lat") or element.get("center", {}).get("lat")
        longitude = element.get("lon") or element.get("center", {}).get("lon")
        if latitude is None or longitude is None:
            continue
        amenity_id = f"osm-{element.get('type', 'node')}-{element.get('id')}"
        if amenity_id in seen:
            continue
        seen.add(amenity_id)
        tags = element.get("tags", {})
        amenities.append(
            MapPoint(
                id=amenity_id,
                title=tags.get("name") or tags.get("brand") or default_title,
                address=_store_address(tags),
                latitude=float(latitude),
                longitude=float(longitude),
                kind=kind,
            )
        )

    amenities.sort(
        key=lambda amenity: min(
            _distance_meters(
                amenity.latitude,
                amenity.longitude,
                point.latitude,
                point.longitude,
            )
            for point in points
        )
    )
    return amenities[:120]


def find_convenience_stores(points: list[MapPoint]) -> list[MapPoint]:
    return _find_osm_amenities(
        points,
        '"shop"="convenience"',
        "store",
        "便利商店",
    )


def find_parking_facilities(points: list[MapPoint]) -> list[MapPoint]:
    return _find_osm_amenities(
        points,
        '"amenity"="parking"',
        "parking",
        "停車場",
    )


def _cached_amenities(
    properties: list[MapPropertyInput],
    field: str,
) -> list[MapPoint]:
    points = {}
    for property_ in properties:
        for amenity in getattr(property_, field):
            points.setdefault(
                f"{amenity.kind}:{amenity.id}",
                MapPoint(
                    id=amenity.id,
                    title=amenity.title,
                    address=amenity.address,
                    latitude=amenity.latitude,
                    longitude=amenity.longitude,
                    kind=amenity.kind,
                ),
            )
    return list(points.values())


def _merge_map_points(*groups: list[MapPoint]) -> list[MapPoint]:
    merged = {}
    for group in groups:
        for point in group:
            merged.setdefault(f"{point.kind}:{point.id}", point)
    return list(merged.values())


def build_map_context(request: MapContextRequest) -> MapContextResponse:
    warnings = []
    region_name = (
        request.region_name.strip()
        or _region_name(request.destination_address or request.destination)
    )

    destination = None
    if (
        request.destination_latitude is not None
        and request.destination_longitude is not None
    ):
        destination = MapPoint(
            id="destination",
            title=request.destination,
            address=request.destination_address or request.destination,
            latitude=request.destination_latitude,
            longitude=request.destination_longitude,
            kind="destination",
        )
    else:
        try:
            destination_location = geocode(f"{request.destination}, 台灣")
            if destination_location:
                latitude, longitude, display_name = destination_location
                destination = MapPoint(
                    id="destination",
                    title=request.destination,
                    address=display_name,
                    latitude=latitude,
                    longitude=longitude,
                    kind="destination",
                )
            else:
                warnings.append("無法精確定位目的地。")
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            warnings.append("目前無法連線到目的地定位服務。")

    properties = []
    for property_ in request.properties:
        try:
            point = _geocode_property(
                property_,
                region_name,
                allow_district_fallback=True,
            )
            if point:
                properties.append(point)
                if point.is_approximate:
                    warnings.append(
                        f"{property_.title} 的刊登地址不完整，"
                        f"地圖僅顯示行政區約略位置。"
                    )
            else:
                warnings.append(f"無法定位房源：{property_.title}")
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            warnings.append(f"定位服務暫時無法處理：{property_.title}")

    if destination is None and properties:
        destination = MapPoint(
            id="destination-area-fallback",
            title=f"{request.destination}生活圈代表點",
            address="目的地無法精確定位，暫以候選房源生活圈中心表示",
            latitude=sum(point.latitude for point in properties) / len(properties),
            longitude=sum(point.longitude for point in properties) / len(properties),
            kind="destination",
            is_approximate=True,
        )
        warnings.append(
            "目的地無法精確定位，地圖暫以候選房源生活圈中心作為代表點。"
        )

    cached_stores = _cached_amenities(
        request.properties,
        "nearby_convenience_stores",
    )
    convenience_stores = cached_stores
    if not all(
        property_.convenience_store_lookup_completed
        for property_ in request.properties
    ):
        try:
            convenience_stores = _merge_map_points(
                cached_stores,
                find_convenience_stores(properties),
            )[:40]
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            warnings.append("目前無法取得附近超商資料。")

    cached_parking = _cached_amenities(
        request.properties,
        "nearby_parking_facilities",
    )
    parking_facilities = cached_parking
    if not all(
        property_.parking_lookup_completed
        for property_ in request.properties
    ):
        try:
            parking_facilities = _merge_map_points(
                cached_parking,
                find_parking_facilities(properties),
            )[:40]
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            warnings.append("目前無法取得附近停車場資料。")

    return MapContextResponse(
        destination=destination,
        properties=properties,
        convenience_stores=convenience_stores,
        parking_facilities=parking_facilities,
        warnings=list(dict.fromkeys(warnings)),
    )
