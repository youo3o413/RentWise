from app.models.schemas import DestinationResolveResponse
from app.services.map_service import geocode, reverse_geocode
from app.services.rent591_service import (
    REGIONS,
    SECTIONS_BY_REGION,
    Rent591Error,
    resolve_591_location,
)


def _region_name(region_id: int) -> str:
    return next(
        (
            name.replace("臺", "台")
            for name, value in REGIONS.items()
            if value == region_id
        ),
        "台灣",
    )


def _district_name(region_id: int, section_id: int | None) -> str:
    if section_id is None:
        return ""
    return next(
        (
            name
            for name, value in SECTIONS_BY_REGION.get(region_id, {}).items()
            if value == section_id
        ),
        "",
    )


def _compact_label(region_name: str, district_name: str, landmark: str) -> str:
    parts = [item for item in (region_name, district_name, landmark) if item]
    return " · ".join(dict.fromkeys(parts))


def resolve_destination(query: str) -> DestinationResolveResponse:
    normalized = query.strip()
    geocode_error: Exception | None = None
    try:
        point = geocode(normalized)
    except Exception as exc:
        geocode_error = exc
        point = None

    if point:
        latitude, longitude, display_name = point
        resolved_address = display_name
        try:
            location = resolve_591_location(display_name)
        except Rent591Error:
            try:
                reverse_address = reverse_geocode(latitude, longitude)
            except Exception:
                reverse_address = None
            if reverse_address:
                resolved_address = f"{display_name}, {reverse_address}"
                location = resolve_591_location(reverse_address)
            else:
                location = resolve_591_location(normalized)
        region_id = location["region"]
        region_name = _region_name(region_id)
        district_name = _district_name(region_id, location.get("section"))
        landmark = display_name.split(",", 1)[0].strip()
        return DestinationResolveResponse(
            query=normalized,
            resolved_label=_compact_label(
                region_name,
                district_name,
                landmark,
            ),
            resolved_address=resolved_address,
            region_name=region_name,
            district_name=district_name,
            latitude=latitude,
            longitude=longitude,
            source="openstreetmap",
            confidence="high",
        )

    try:
        location = resolve_591_location(normalized)
    except Rent591Error as exc:
        if geocode_error:
            raise Rent591Error(
                "地理定位服務暫時無法使用，且目前無法從行政區規則辨識此地名。"
            ) from geocode_error
        raise Rent591Error(
            f"找不到「{normalized}」的具體位置，請換一個地標或地址。"
        ) from exc

    region_id = location["region"]
    region_name = _region_name(region_id)
    district_name = _district_name(region_id, location.get("section"))
    return DestinationResolveResponse(
        query=normalized,
        resolved_label=_compact_label(
            region_name,
            district_name,
            normalized,
        ),
        resolved_address="".join(
            item for item in (region_name, district_name, normalized)
            if item
        ),
        region_name=region_name,
        district_name=district_name,
        source="administrative_rules",
        confidence="medium",
    )
