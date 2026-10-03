from app.services import destination_service
from app.services.destination_service import resolve_destination


def test_abstract_landmark_is_resolved_to_concrete_address(monkeypatch):
    monkeypatch.setattr(
        destination_service,
        "geocode",
        lambda query: (
            24.9781107,
            121.5467767,
            "Yes!Life裕隆城, 中興路三段, 新店區, 新北市, 台灣",
        ),
    )

    result = resolve_destination("裕隆城")

    assert result.region_name == "新北市"
    assert result.district_name == "新店區"
    assert result.resolved_label == "新北市 · 新店區 · Yes!Life裕隆城"
    assert result.source == "openstreetmap"


def test_sparse_landmark_result_uses_reverse_geocoding_for_district(monkeypatch):
    monkeypatch.setattr(
        destination_service,
        "geocode",
        lambda query: (25.0434703, 121.5071938, "西門町商圈, 臺灣"),
    )
    monkeypatch.setattr(
        destination_service,
        "reverse_geocode",
        lambda latitude, longitude: "峨眉街, 萬華區, 臺北市, 臺灣",
    )

    result = resolve_destination("西門町")

    assert result.region_name == "台北市"
    assert result.district_name == "萬華區"
    assert result.resolved_label == "台北市 · 萬華區 · 西門町商圈"
    assert "峨眉街" in result.resolved_address


def test_taida_alias_is_geocoded_inside_taipei_not_tainan(monkeypatch):
    queries = []

    def fake_geocode(query: str):
        queries.append(query)
        return (
            25.0173,
            121.5398,
            "國立台灣大學, 大安區, 台北市, 台灣",
        )

    monkeypatch.setattr(destination_service, "geocode", fake_geocode)

    result = resolve_destination("台大")

    assert queries == ["台大, 大安區, 台北市, 台灣"]
    assert result.region_name == "台北市"
    assert result.district_name == "大安區"
    assert result.latitude == 25.0173


def test_taida_alias_rejects_wrong_tainan_geocode_result(monkeypatch):
    monkeypatch.setattr(
        destination_service,
        "geocode",
        lambda query: (22.99, 120.21, "測試地點, 台南市, 台灣"),
    )

    result = resolve_destination("台大")

    assert result.region_name == "台北市"
    assert result.district_name == "大安區"
    assert result.latitude is None
    assert result.source == "administrative_rules"
