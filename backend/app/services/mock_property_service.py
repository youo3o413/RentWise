"""Fixed fictional NTU listings; no listing website or image requests."""

import json
from pathlib import Path

from app.models.schemas import Property, UserRequirements

MOCK_DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "mock_properties.json"
NTU_COORDINATES = (25.0174, 121.5397)
NTU_ALIASES = {"台大", "台灣大學", "國立台灣大學", "台灣大學（台北公館校區）", "國立台灣大學（台北公館校區）"}


def is_ntu_destination(destination: str) -> bool:
    return destination.replace("臺", "台").strip() in NTU_ALIASES


def load_mock_properties(req: UserRequirements) -> list[Property]:
    # Parse fresh objects on each request; feedback/analysis must not mutate the fixture.
    properties = [
        Property.model_validate(item)
        for item in json.loads(MOCK_DATA_PATH.read_text(encoding="utf-8"))
    ]
    for item in properties:
        item.listing_text_source = "mock"
        # Listings have no external detail links; bundled photos remain available.
        item.source_url = ""
        item.source_links = []
        if is_ntu_destination(req.destination):
            item.commute_minutes = (
                item.driving_commute_minutes
                if req.commute_mode == "drive"
                else item.walking_commute_minutes
            )
            item.commute_method = (
                "預估駕車時間（非實測）"
                if req.commute_mode == "drive"
                else "預估步行時間（非實測）"
            )
        else:
            # NTU demo times cannot describe a different destination.
            item.commute_minutes = None
            item.walking_commute_minutes = None
            item.driving_commute_minutes = None
            item.transit_commute_minutes = None
            item.walking_distance_km = None
            item.driving_distance_km = None
            item.route_distance_km = None
            item.commute_method = ""
            item.distance_reference = ""
    return properties
