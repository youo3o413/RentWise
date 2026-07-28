from app.models.schemas import MapContextRequest, MapPoint
from app.services import map_service


def test_property_geocode_reorders_district_and_street(monkeypatch):
    queries = []

    def fake_geocode(query: str):
        queries.append(query)
        if query == "指南路三段22巷, 文山區, 台北市, 台灣":
            return 24.9838851, 121.5793204, "指南路三段22巷"
        return None

    monkeypatch.setattr(map_service, "geocode", fake_geocode)

    point = map_service.geocode_property_address(
        id_="591-address-test",
        title="指南路套房",
        address="文山區-指南路三段22巷",
        destination="政治大學",
    )

    assert queries[0] == "指南路三段22巷, 文山區, 台北市, 台灣"
    assert point is not None
    assert point.latitude == 24.9838851
    assert point.longitude == 121.5793204


def test_build_map_context_returns_destination_properties_and_stores(monkeypatch):
    def fake_geocode(query: str):
        if "政治大學" in query:
            return 24.9877, 121.5771, "國立政治大學"
        return 24.9901, 121.5732, "台北市文山區指南路"

    def fake_stores(points):
        assert len(points) == 1
        return [
            MapPoint(
                id="osm-node-1",
                title="測試便利商店",
                address="台北市文山區",
                latitude=24.9902,
                longitude=121.5733,
                kind="store",
            )
        ]

    monkeypatch.setattr(map_service, "geocode", fake_geocode)
    monkeypatch.setattr(map_service, "find_convenience_stores", fake_stores)
    monkeypatch.setattr(map_service, "find_parking_facilities", lambda points: [])

    result = map_service.build_map_context(
        MapContextRequest(
            destination="政治大學",
            properties=[
                {
                    "id": "591-123",
                    "title": "政大附近套房",
                    "address": "文山區-指南路二段",
                    "score": 88,
                    "source_url": "https://rent.591.com.tw/123",
                }
            ],
        )
    )

    assert result.destination is not None
    assert result.destination.title == "政治大學"
    assert result.properties[0].score == 88
    assert result.convenience_stores[0].title == "測試便利商店"
    assert result.warnings == []


def test_map_context_keeps_partial_results_when_address_not_found(monkeypatch):
    monkeypatch.setattr(map_service, "geocode", lambda query: None)
    monkeypatch.setattr(map_service, "find_convenience_stores", lambda points: [])
    monkeypatch.setattr(map_service, "find_parking_facilities", lambda points: [])

    result = map_service.build_map_context(
        MapContextRequest(
            destination="不存在的地點",
            properties=[
                {
                    "id": "listing-1",
                    "title": "地址不完整房源",
                    "address": "某路",
                    "score": 70,
                }
            ],
        )
    )

    assert result.destination is None
    assert result.properties == []
    assert len(result.warnings) == 2


def test_map_context_uses_property_area_center_when_abstract_destination_fails(
    monkeypatch,
):
    def fake_geocode(query: str):
        if "抽象商圈" in query:
            return None
        return 25.04, 121.50, "台北市萬華區測試路"

    monkeypatch.setattr(map_service, "geocode", fake_geocode)
    monkeypatch.setattr(map_service, "find_convenience_stores", lambda points: [])
    monkeypatch.setattr(map_service, "find_parking_facilities", lambda points: [])

    result = map_service.build_map_context(
        MapContextRequest(
            destination="抽象商圈",
            properties=[
                {
                    "id": "listing-1",
                    "title": "生活圈房源",
                    "address": "萬華區測試路",
                    "score": 80,
                }
            ],
        )
    )

    assert result.destination is not None
    assert result.destination.is_approximate is True
    assert result.destination.latitude == 25.04
    assert "生活圈代表點" in result.destination.title
    assert any("生活圈中心" in warning for warning in result.warnings)


def test_map_context_reuses_location_agent_amenities_without_querying_again(
    monkeypatch,
):
    def unexpected_lookup(points):
        raise AssertionError("地圖不應重複查詢 Location Agent 已取得的設施")

    monkeypatch.setattr(
        map_service,
        "find_convenience_stores",
        unexpected_lookup,
    )
    monkeypatch.setattr(
        map_service,
        "find_parking_facilities",
        unexpected_lookup,
    )

    result = map_service.build_map_context(
        MapContextRequest(
            destination="政治大學",
            destination_address="台北市文山區指南路二段64號",
            destination_latitude=24.9877,
            destination_longitude=121.5771,
            properties=[
                {
                    "id": "listing-1",
                    "title": "政大附近套房",
                    "address": "台北市文山區指南路",
                    "score": 88,
                    "latitude": 24.9901,
                    "longitude": 121.5732,
                    "convenience_store_lookup_completed": True,
                    "nearby_convenience_stores": [
                        {
                            "id": "osm-store-1",
                            "title": "附近超商",
                            "address": "台北市文山區",
                            "latitude": 24.9902,
                            "longitude": 121.5733,
                            "kind": "store",
                        }
                    ],
                    "parking_lookup_completed": True,
                    "nearby_parking_facilities": [
                        {
                            "id": "osm-parking-1",
                            "title": "附近停車場",
                            "address": "台北市文山區",
                            "latitude": 24.9903,
                            "longitude": 121.5734,
                            "kind": "parking",
                        }
                    ],
                }
            ],
        )
    )

    assert [store.id for store in result.convenience_stores] == ["osm-store-1"]
    assert [parking.id for parking in result.parking_facilities] == [
        "osm-parking-1"
    ]
    assert result.warnings == []
