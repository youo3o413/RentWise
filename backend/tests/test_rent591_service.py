import pytest

from app.models.schemas import UserRequirements
from app.services.rent591_service import (
    Rent591Error,
    build_591_search_url,
    parse_591_listings,
    resolve_591_location,
)


LISTING_HTML = """
<div class="item" data-id="12345678">
  <div class="item-img">
    <img data-src="https://img1.591.com.tw/example.jpg" />
  </div>
  <div class="item-info">
    <div class="item-info-title">
      <a class="link v-middle" href="https://rent.591.com.tw/12345678"
         title="政大採光安靜套房">政大採光安靜套房</a>
    </div>
    <div class="item-info-tag"><span class="tag">有電梯</span></div>
    <div class="item-info-txt"><span>獨立套房</span><div>8坪</div><div>5F/8F</div></div>
    <div class="item-info-txt"><span><div>文山區-指南路二段</div></span></div>
    <div class="item-info-txt"><span>距政治大學</span><strong>700公尺</strong></div>
    <div class="item-info-price"><strong><div>12,500</div></strong><span>元/月</span></div>
  </div>
</div>
"""


def test_build_search_url_uses_requirements():
    req = UserRequirements(
        budget=15000,
        destination="政治大學",
        needs_elevator=True,
        preferences=["可開伙"],
    )
    url = build_591_search_url(req)
    assert "school=401" in url
    assert "price=0_15000" in url
    assert "other=lift%2Ccook" in url


@pytest.mark.parametrize(
    ("destination", "expected"),
    [
        ("台灣大學", {"region": 1, "section": 5}),
        ("內湖", {"region": 1, "section": 10}),
        ("台北市信義區", {"region": 1, "section": 7}),
        ("台中市西屯區", {"region": 8, "section": 104}),
        ("高雄市左營區", {"region": 17, "section": 253}),
        ("花蓮縣", {"region": 23}),
    ],
)
def test_resolve_destination(destination, expected):
    assert resolve_591_location(destination) == expected


def test_ambiguous_district_requires_city():
    with pytest.raises(Rent591Error):
        resolve_591_location("大安區")


def test_parse_591_listing():
    properties = parse_591_listings(LISTING_HTML)
    assert len(properties) == 1
    property_ = properties[0]
    assert property_.id == "591-12345678"
    assert property_.rent == 12500
    assert property_.has_window is True
    assert property_.has_elevator is True
    assert property_.floor == 5
    assert property_.source_url == "https://rent.591.com.tw/12345678"


def test_parse_591_listing_detects_rental_subsidy_tag():
    html = LISTING_HTML.replace("有電梯", "有電梯 可租補")
    property_ = parse_591_listings(html)[0]

    assert property_.rental_subsidy_eligible is True


def test_explicit_no_rental_subsidy_takes_precedence():
    html = LISTING_HTML.replace("有電梯", "有電梯 不可租補")
    property_ = parse_591_listings(html)[0]

    assert property_.rental_subsidy_eligible is False


def test_parse_591_listing_excludes_parking_space():
    html = (
        LISTING_HTML
        .replace("政大採光安靜套房", "坡道平面車位出租")
        .replace(
            "<span>獨立套房</span><div>8坪</div><div>5F/8F</div>",
            "<span>車位</span><div>B2F</div>",
        )
    )

    assert parse_591_listings(html) == []


def test_parse_591_listing_marks_included_water_and_visible_subsidy():
    html = LISTING_HTML.replace(
        '<div class="item-info-price">',
        "<div>租金含水費・可申請300億中央擴大租金補貼</div>"
        '<div class="item-info-price">',
    )

    property_ = parse_591_listings(html)[0]

    assert property_.water_fee == 0
    assert property_.water_fee_disclosed is True
    assert property_.electricity_rate == 5
    assert property_.electricity_rate_disclosed is False
    assert property_.rental_subsidy_eligible is True
