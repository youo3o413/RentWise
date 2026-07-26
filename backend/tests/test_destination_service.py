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
