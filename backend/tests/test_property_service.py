from app.models.schemas import Property, PropertySourceLink
from app.services.property_service import merge_and_dedupe_properties


def make_property(
    property_id: str,
    source_name: str,
    source_url: str,
    title: str = "明亮套房",
) -> Property:
    return Property(
        id=property_id,
        title=title,
        address="台北市文山區指南路二段45巷",
        rent=12500,
        management_fee=0,
        water_fee=0,
        electricity_rate=5,
        estimated_kwh=100,
        commute_minutes=None,
        has_window=None,
        window_type="未揭露",
        has_elevator=None,
        floor=None,
        noise_level=None,
        nearby=[],
        features=[],
        risks=[],
        description="",
        image_url="https://example.com/house.jpg",
        source_name=source_name,
        source_url=source_url,
        source_links=[
            PropertySourceLink(name=source_name, url=source_url)
        ],
    )


def test_merge_duplicate_keeps_both_source_links():
    from_591 = make_property(
        "591-1",
        "591租屋",
        "https://rent.591.com.tw/1",
    )
    from_housefun = make_property(
        "housefun-2",
        "好房網快租",
        "https://rent.housefun.com.tw/rent/house/2/",
    )

    result = merge_and_dedupe_properties([[from_591], [from_housefun]])

    assert len(result) == 1
    assert result[0].source_name == "591租屋／好房網快租"
    assert {link.name for link in result[0].source_links} == {
        "591租屋",
        "好房網快租",
    }


def test_merge_processes_later_sources_before_limit():
    first = make_property("591-1", "591租屋", "https://rent.591.com.tw/1")
    second = make_property(
        "591-2",
        "591租屋",
        "https://rent.591.com.tw/2",
        title="另一間房",
    ).model_copy(update={"address": "台北市文山區木柵路一段", "rent": 14000})
    duplicate = make_property(
        "housefun-3",
        "好房網快租",
        "https://rent.housefun.com.tw/rent/house/3/",
    )

    result = merge_and_dedupe_properties(
        [[first, second], [duplicate]],
        limit=2,
    )

    assert len(result) == 2
    assert len(result[0].source_links) == 2


def test_merge_keeps_more_explicit_cost_and_subsidy_data():
    from_591 = make_property(
        "591-1",
        "591租屋",
        "https://rent.591.com.tw/1",
    ).model_copy(
        update={
            "water_fee_disclosed": False,
            "rental_subsidy_eligible": None,
        }
    )
    from_housefun = make_property(
        "housefun-2",
        "好房網快租",
        "https://rent.housefun.com.tw/rent/house/2/",
    ).model_copy(
        update={
            "water_fee": 0,
            "water_fee_disclosed": True,
            "rental_subsidy_eligible": True,
        }
    )

    result = merge_and_dedupe_properties([[from_591], [from_housefun]])

    assert result[0].water_fee == 0
    assert result[0].water_fee_disclosed is True
    assert result[0].rental_subsidy_eligible is True


def test_merge_excludes_parking_only_listing():
    parking = make_property(
        "591-parking",
        "591租屋",
        "https://rent.591.com.tw/parking",
        title="坡道平面車位出租",
    ).model_copy(update={"description": "地下二樓汽車位月租"})

    assert merge_and_dedupe_properties([[parking]]) == []


def test_merge_excludes_storage_only_listing():
    storage = make_property(
        "591-storage",
        "591租屋",
        "https://rent.591.com.tw/storage",
        title="迷你置物空間出租",
    ).model_copy(update={"description": "僅供置物，不得居住或過夜"})

    assert merge_and_dedupe_properties([[storage]]) == []
