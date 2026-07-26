import pytest

from app.models.schemas import MapPoint, Property
from app.services import commute_service


def _property() -> Property:
    return Property(
        id="591-1",
        title="測試房源",
        address="文山區-指南路二段",
        rent=12000,
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
        image_url="https://example.com/image.jpg",
    )


@pytest.fixture(autouse=True)
def disable_live_store_lookup(monkeypatch):
    monkeypatch.setattr(
        commute_service,
        "find_convenience_stores",
        lambda points: [],
    )
    monkeypatch.setattr(
        commute_service,
        "find_parking_facilities",
        lambda points: [],
    )
    monkeypatch.setattr(
        commute_service,
        "_driving_commutes",
        lambda destination, points: {},
    )


def test_enrich_commute_data_uses_walking_route(monkeypatch):
    monkeypatch.setattr(
        commute_service,
        "geocode",
        lambda query: (24.9802, 121.5750, "政治大學"),
    )
    monkeypatch.setattr(
        commute_service,
        "geocode_property_address",
        lambda **kwargs: MapPoint(
            id=kwargs["id_"],
            title=kwargs["title"],
            address=kwargs["address"],
            latitude=24.9857,
            longitude=121.5798,
            kind="property",
        ),
    )
    monkeypatch.setattr(
        commute_service,
        "_walking_commutes",
        lambda destination, points: {"591-1": (8, 2.4)},
    )
    monkeypatch.setattr(commute_service, "transit_commutes", lambda *args: {})

    result = commute_service.enrich_commute_data([_property()], "政治大學")[0]

    assert result.commute_minutes == 8
    assert result.route_distance_km == 2.4
    assert result.commute_method == "Valhalla 步行路網"
    assert result.latitude == 24.9857


def test_enrich_commute_data_falls_back_when_router_unavailable(monkeypatch):
    monkeypatch.setattr(
        commute_service,
        "geocode",
        lambda query: (24.9802, 121.5750, "政治大學"),
    )
    monkeypatch.setattr(
        commute_service,
        "geocode_property_address",
        lambda **kwargs: MapPoint(
            id=kwargs["id_"],
            title=kwargs["title"],
            address=kwargs["address"],
            latitude=24.9857,
            longitude=121.5798,
            kind="property",
        ),
    )
    monkeypatch.setattr(commute_service, "_walking_commutes", lambda *args: {})
    monkeypatch.setattr(commute_service, "transit_commutes", lambda *args: {})

    result = commute_service.enrich_commute_data([_property()], "政治大學")[0]

    assert result.commute_minutes is not None
    assert result.commute_method == "地理距離步行推估"


def test_enrich_commute_data_prefers_tdx_transit(monkeypatch):
    monkeypatch.setattr(
        commute_service,
        "geocode",
        lambda query: (24.9802, 121.5750, "政治大學"),
    )
    monkeypatch.setattr(
        commute_service,
        "geocode_property_address",
        lambda **kwargs: MapPoint(
            id=kwargs["id_"],
            title=kwargs["title"],
            address=kwargs["address"],
            latitude=24.9857,
            longitude=121.5798,
            kind="property",
        ),
    )
    monkeypatch.setattr(
        commute_service,
        "_walking_commutes",
        lambda *args: {"591-1": (22, 1.6)},
    )
    monkeypatch.setattr(
        commute_service,
        "transit_commutes",
        lambda *args: {"591-1": (14, 1)},
    )

    result = commute_service.enrich_commute_data([_property()], "政治大學")[0]

    assert result.commute_minutes == 14
    assert result.commute_transfers == 1
    assert result.commute_method == "TDX 大眾運輸＋步行"
    assert result.route_distance_km is None


def test_enrich_commute_data_uses_map_store_results(monkeypatch):
    monkeypatch.setattr(
        commute_service,
        "geocode",
        lambda query: (24.9802, 121.5750, "政治大學"),
    )
    monkeypatch.setattr(
        commute_service,
        "geocode_property_address",
        lambda **kwargs: MapPoint(
            id=kwargs["id_"],
            title=kwargs["title"],
            address=kwargs["address"],
            latitude=24.9857,
            longitude=121.5798,
            kind="property",
        ),
    )
    monkeypatch.setattr(commute_service, "_walking_commutes", lambda *args: {})
    monkeypatch.setattr(commute_service, "transit_commutes", lambda *args: {})
    monkeypatch.setattr(
        commute_service,
        "find_convenience_stores",
        lambda points: [
            MapPoint(
                id="osm-node-1",
                title="附近超商",
                address="台北市文山區",
                latitude=24.9860,
                longitude=121.5800,
                kind="store",
            ),
            MapPoint(
                id="osm-node-2",
                title="太遠的超商",
                address="台北市文山區",
                latitude=25.0,
                longitude=121.6,
                kind="store",
            ),
        ],
    )

    result = commute_service.enrich_commute_data([_property()], "政治大學")[0]

    assert result.nearby_convenience_store_count == 1
    assert result.nearest_convenience_store_meters is not None
    assert result.nearest_convenience_store_meters < 500
    assert result.nearby_data_source == "OpenStreetMap"
    assert "便利商店" in result.nearby


def test_enrich_commute_data_uses_driving_and_parking(monkeypatch):
    monkeypatch.setattr(
        commute_service,
        "geocode",
        lambda query: (24.9802, 121.5750, "政治大學"),
    )
    monkeypatch.setattr(
        commute_service,
        "geocode_property_address",
        lambda **kwargs: MapPoint(
            id=kwargs["id_"],
            title=kwargs["title"],
            address=kwargs["address"],
            latitude=24.9857,
            longitude=121.5798,
            kind="property",
        ),
    )
    monkeypatch.setattr(commute_service, "_walking_commutes", lambda *args: {})
    monkeypatch.setattr(commute_service, "transit_commutes", lambda *args: {})
    monkeypatch.setattr(
        commute_service,
        "_driving_commutes",
        lambda *args: {"591-1": (12, 5.4)},
    )
    monkeypatch.setattr(
        commute_service,
        "find_parking_facilities",
        lambda points: [
            MapPoint(
                id="osm-way-parking",
                title="測試停車場",
                address="台北市文山區",
                latitude=24.9860,
                longitude=121.5800,
                kind="parking",
            )
        ],
    )

    result = commute_service.enrich_commute_data(
        [_property()],
        "政治大學",
        commute_mode="drive",
        needs_parking=True,
    )[0]

    assert result.commute_minutes == 12
    assert result.commute_method == "Valhalla 駕車路網"
    assert result.driving_distance_km == 5.4
    assert result.nearby_parking_count == 1
    assert result.nearest_parking_meters is not None
