from app.services.listing_text_service import (
    is_parking_only_listing,
    parse_listing_costs,
    rental_subsidy_status,
)


def test_listing_costs_preserve_included_and_explicit_fees():
    included = parse_listing_costs("租金已含水費，電費每度 5.5 元")
    assert included.water_fee == 0
    assert included.water_fee_disclosed is True
    assert included.electricity_rate == 5.5
    assert included.electricity_rate_disclosed is True
    assert included.electricity_usage_disclosed is False

    fixed = parse_listing_costs("管理費每月 800 元，水費每月 200 元")
    assert fixed.management_fee == 800
    assert fixed.management_fee_disclosed is True
    assert fixed.water_fee == 200
    assert fixed.water_fee_disclosed is True


def test_rental_subsidy_recognizes_more_visible_labels():
    assert rental_subsidy_status("租補友善，可報稅") is True
    assert rental_subsidy_status("可申請300億中央擴大租金補貼") is True
    assert rental_subsidy_status("租補需確認") is None
    assert rental_subsidy_status("不配合租金補貼") is False


def test_parking_filter_keeps_homes_that_include_a_parking_space():
    assert is_parking_only_listing("坡道平面車位出租", "車位") is True
    assert is_parking_only_listing("大樓地下汽車位月租", "") is True
    assert is_parking_only_listing("三房住家附平面車位", "整層住家") is False
