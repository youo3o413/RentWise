import pytest

from app.models.schemas import UserRequirements
from app.services.source_planning_service import build_source_search_plan
from app.config import get_settings


@pytest.fixture(autouse=True)
def enable_live_source_planning_for_legacy_tests(monkeypatch):
    monkeypatch.setattr(get_settings(), "live_listing_sources_enabled", True)


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
    if destination == "政治大學":
        assert plan.district_name == "文山區"


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
    assert plan.district_name == "新店區"
    assert "新店區" in plan.resolved_address
    assert plan.latitude == 24.978


def test_original_taida_rule_overrides_wrong_resolved_tainan_address():
    plan = build_source_search_plan(
        UserRequirements(
            destination="台大",
            destination_resolved_address="測試地點, 台南市, 台灣",
            destination_latitude=22.99,
            destination_longitude=120.21,
            property_source="multi",
        )
    )

    assert plan.region_name == "台北市"
    assert plan.district_name == "大安區"
    assert plan.latitude is None
    assert plan.longitude is None
    assert plan.resolved_address == "台北市大安區台大"
    assert "台南市" not in plan.resolved_address
