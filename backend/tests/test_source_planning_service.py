import pytest

from app.models.schemas import UserRequirements
from app.services.source_planning_service import build_source_search_plan


@pytest.mark.parametrize(
    ("destination", "region_name"),
    [
        ("政治大學", "台北市"),
        ("輔仁大學", "新北市"),
    ],
)
def test_plan_follows_user_destination(destination, region_name):
    req = UserRequirements(destination=destination, property_source="multi")
    plan = build_source_search_plan(req)

    assert plan.destination == destination
    assert plan.region_name == region_name
    assert plan.keywords[0] == destination
    assert plan.sources == ("591租屋", "好房網快租")


def test_unknown_landmark_uses_geocoded_address_for_region(monkeypatch):
    monkeypatch.setattr(
        "app.services.destination_service.geocode",
        lambda query: (
            24.978,
            121.547,
            "裕隆城, 寶橋路, 新店區, 新北市, 台灣",
        ),
    )

    plan = build_source_search_plan(
        UserRequirements(destination="裕隆城", property_source="multi")
    )

    assert plan.destination == "裕隆城"
    assert plan.region_name == "新北市"
    assert "新店區" in plan.resolved_address
    assert plan.latitude == 24.978
