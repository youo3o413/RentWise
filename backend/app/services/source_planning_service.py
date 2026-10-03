from dataclasses import dataclass

from app.config import use_mock_listings
from app.models.schemas import UserRequirements
from app.services.mock_property_service import NTU_COORDINATES, is_ntu_destination
from app.services.destination_service import resolve_destination
from app.services.rent591_service import (
    REGIONS,
    SECTIONS_BY_REGION,
    Rent591Error,
    resolve_591_location,
)


@dataclass(frozen=True)
class SourceSearchPlan:
    destination: str
    region_name: str
    keywords: tuple[str, ...]
    sources: tuple[str, ...]
    district_name: str = ""
    resolved_address: str = ""
    latitude: float | None = None
    longitude: float | None = None


def build_source_search_plan(req: UserRequirements) -> SourceSearchPlan:
    mock = use_mock_listings(req.property_source)
    if mock and is_ntu_destination(req.destination):
        return SourceSearchPlan(
            destination=req.destination,
            region_name="台北市",
            district_name="大安區",
            keywords=(req.destination,),
            sources=("台大周邊房源資料",),
            resolved_address="台北市大安區台灣大學（公館校區示意位置）",
            latitude=NTU_COORDINATES[0],
            longitude=NTU_COORDINATES[1],
        )
    resolved_address = (
        req.destination_resolved_address.strip() or req.destination.strip()
    )
    latitude = req.destination_latitude
    longitude = req.destination_longitude
    try:
        # 使用者原始地名的明確規則優先於外部 geocoder，例如「台大」固定是
        # 台北市大安區，不能被同名搜尋結果改成台南。
        location = resolve_591_location(req.destination)
    except Rent591Error:
        try:
            location = resolve_591_location(resolved_address)
        except Rent591Error:
            resolved = resolve_destination(req.destination)
            latitude = resolved.latitude
            longitude = resolved.longitude
            resolved_address = resolved.resolved_address
            location = resolve_591_location(resolved_address)
    else:
        expected_region = next(
            (
                name.replace("臺", "台")
                for name, value in REGIONS.items()
                if value == location["region"]
            ),
            "",
        )
        expected_district = next(
            (
                name
                for name, value in SECTIONS_BY_REGION.get(
                    location["region"],
                    {},
                ).items()
                if value == location.get("section")
            ),
            "",
        )
        if not expected_district and location.get("school") == 401:
            expected_district = "文山區"
        if (
            expected_region
            and expected_region not in resolved_address.replace("臺", "台")
        ):
            resolved_address = (
                f"{expected_region}{expected_district}{req.destination}"
            )
            latitude = None
            longitude = None
    region_id = location["region"]
    region_name = next(
        (
            name.replace("臺", "台")
            for name, value in REGIONS.items()
            if value == region_id
        ),
        "台灣",
    )
    section_id = location.get("section")
    district_name = next(
        (
            name
            for name, value in SECTIONS_BY_REGION.get(region_id, {}).items()
            if value == section_id
        ),
        "",
    )
    if not district_name and location.get("school") == 401:
        district_name = "文山區"
    normalized_destination = req.destination.strip()
    keywords = tuple(
        dict.fromkeys(
            [
                normalized_destination,
                normalized_destination.replace("臺", "台"),
            ]
        )
    )
    sources = (
        ("台大周邊房源資料",)
        if mock else ("591租屋", "好房網快租")
        if req.property_source == "multi"
        else ("591租屋",)
    )
    return SourceSearchPlan(
        destination=normalized_destination,
        region_name=region_name,
        district_name=district_name,
        keywords=keywords,
        sources=sources,
        resolved_address=resolved_address,
        latitude=latitude,
        longitude=longitude,
    )
