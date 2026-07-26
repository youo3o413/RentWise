from app.services.housefun_service import (
    _decode_strings,
    _encode_strings,
    parse_housefun_listings,
)


LISTING_HTML = """
<article class="DataList">
  <div class="photo">
    <img src="https://example.com/house.jpg">
  </div>
  <h3 class="title">
    <a href="/rent/house/987654/" title="政大明亮電梯套房">政大明亮電梯套房</a>
  </h3>
  <div class="addr">台北市文山區指南路二段</div>
  <div>租金：13,500 元/月</div>
  <div>坪數：9.5 坪</div>
  <div>樓層：5 / 8 樓</div>
  <div>1房(室)1廳1衛</div>
  <div>電梯大樓</div>
  <a href="/map?LatLng=24.9876,121.5764">地圖</a>
</article>
"""


def test_request_string_codec_round_trip():
    value = {
        "DataUnit": "1",
        "KeyWord": "政治大學",
        "nested": ["台北市", 15000],
    }
    assert _decode_strings(_encode_strings(value)) == value


def test_parse_housefun_listing():
    properties = parse_housefun_listings(LISTING_HTML)
    assert len(properties) == 1
    property_ = properties[0]
    assert property_.id == "housefun-987654"
    assert property_.title == "政大明亮電梯套房"
    assert property_.rent == 13500
    assert property_.floor == 5
    assert property_.has_elevator is True
    assert property_.latitude == 24.9876
    assert property_.longitude == 121.5764
    assert property_.source_links[0].name == "好房網快租"


def test_housefun_excludes_parking_and_parses_included_water():
    parking_html = LISTING_HTML.replace(
        "政大明亮電梯套房",
        "坡道機械車位出租",
    ).replace("1房(室)1廳1衛", "地下二樓停車位")
    assert parse_housefun_listings(parking_html) == []

    included_water_html = LISTING_HTML.replace(
        "<div>電梯大樓</div>",
        "<div>電梯大樓・房租含水費・可租補</div>",
    )
    property_ = parse_housefun_listings(included_water_html)[0]
    assert property_.water_fee == 0
    assert property_.water_fee_disclosed is True
    assert property_.electricity_rate_disclosed is False
    assert property_.rental_subsidy_eligible is True
