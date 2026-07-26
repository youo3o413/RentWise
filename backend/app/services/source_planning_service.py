from dataclasses import dataclass

from app.models.schemas import UserRequirements
from app.services.destination_service import resolve_destination
from app.services.rent591_service import REGIONS, Rent591Error, resolve_591_location


@dataclass(frozen=True)
class SourceSearchPlan:
    destination: str
    region_name: str
    keywords: tuple[str, ...]
    sources: tuple[str, ...]
    resolved_address: str = ""
    latitude: float | None = None
    longitude: float | None = None


def build_source_search_plan(req: UserRequirements) -> SourceSearchPlan:
    resolved_address = (
        req.destination_resolved_address.strip() or req.destination.strip()
    )
    latitude = req.destination_latitude
    longitude = req.destination_longitude
    try:
        location = resolve_591_location(resolved_address)
    except Rent591Error:
        resolved = resolve_destination(req.destination)
        latitude = resolved.latitude
        longitude = resolved.longitude
        resolved_address = resolved.resolved_address
        location = resolve_591_location(resolved_address)
    region_id = location["region"]
    region_name = next(
        (
            name.replace("臺", "台")
            for name, value in REGIONS.items()
            if value == region_id
        ),
        "台灣",
    )
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
        ("591租屋", "好房網快租")
        if req.property_source == "multi"
        else ("591租屋",)
    )
    return SourceSearchPlan(
        destination=normalized_destination,
        region_name=region_name,
        keywords=keywords,
        sources=sources,
        resolved_address=resolved_address,
        latitude=latitude,
        longitude=longitude,
    )
