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


def test_property_geocode_falls_back_from_masked_591_house_number(monkeypatch):
    queries = []

    def fake_geocode(query: str):
        queries.append(query)
        if query == "木柵路四段, 文山區, 台北市, 台灣":
            return 24.995, 121.57, "台北市文山區木柵路四段"
        return None

    monkeypatch.setattr(map_service, "geocode", fake_geocode)

    point = map_service.geocode_property_address(
        id_="591-masked-address",
        title="木柵路套房",
        address="台北市文山區木柵路四段XX號7樓",
        destination="台北市內湖區",
    )

    assert queries == [
        "木柵路四段XX號, 文山區, 台北市, 台灣",
        "台北市文山區木柵路四段XX號, 台灣",
        "木柵路四段, 文山區, 台北市, 台灣",
    ]
    assert point is not None
    assert point.latitude == 24.995
    assert point.longitude == 121.57


def test_property_geocode_supports_compact_taiwan_address(monkeypatch):
    queries = []

    def fake_geocode(query: str):
        queries.append(query)
        if query == "台北市文山區指南路二段, 台灣":
            return 24.99, 121.575, "台北市文山區指南路二段"
        return None

    monkeypatch.setattr(map_service, "geocode", fake_geocode)

    point = map_service.geocode_property_address(
        id_="compact-address",
        title="指南路房源",
        address="文山區-指南路二段",
        destination="政治大學",
    )

    assert queries == [
        "指南路二段, 文山區, 台北市, 台灣",
        "台北市文山區指南路二段, 台灣",
    ]
    assert point is not None
    assert point.latitude == 24.99


def test_property_geocode_combines_known_county_with_township(monkeypatch):
    queries = []

    def fake_geocode(query: str):
        queries.append(query)
        if query == "彰化縣大村鄉山腳路, 台灣":
            return 23.991, 120.588, "彰化縣大村鄉山腳路"
        return None

    monkeypatch.setattr(map_service, "geocode", fake_geocode)

    point = map_service.geocode_property_address(
        id_="changhua-address",
        title="大村鄉套房",
        address="大村鄉山腳路",
        destination="大葉大學",
        region_name="彰化縣",
    )

    assert queries == [
        "山腳路, 大村鄉, 彰化縣, 台灣",
        "彰化縣大村鄉山腳路, 台灣",
    ]
    assert point is not None
    assert point.latitude == 23.991
    assert point.longitude == 120.588


def test_property_geocode_supports_town_and_county_admin_names():
    assert (
        map_service._clean_listing_address("彰化縣大村鄉山腳路")
        == "山腳路, 大村鄉"
    )
    assert (
        map_service._clean_listing_address("彰化縣員林市中山路一段")
        == "中山路一段, 員林市"
    )
    assert (
        map_service._clean_listing_address("彰化縣溪湖鎮彰水路")
        == "彰水路, 溪湖鎮"
    )


def test_map_uses_district_fallback_without_using_it_for_commute(monkeypatch):
    def fake_geocode(query: str):
        if query == "文山區, 台北市, 台灣":
            return 24.99, 121.57, "台北市文山區"
        return None

    monkeypatch.setattr(map_service, "geocode", fake_geocode)
    monkeypatch.setattr(map_service, "find_convenience_stores", lambda points: [])
    monkeypatch.setattr(map_service, "find_parking_facilities", lambda points: [])

    commute_point = map_service.geocode_property_address(
        id_="incomplete-address",
        title="地址不完整房源",
        address="文山區-未收錄道路XX號",
        destination="政治大學",
    )
    result = map_service.build_map_context(
        MapContextRequest(
            destination="政治大學",
            destination_latitude=24.9877,
            destination_longitude=121.5771,
            properties=[
                {
                    "id": "incomplete-address",
                    "title": "地址不完整房源",
                    "address": "文山區-未收錄道路XX號",
                    "score": 70,
                }
            ],
        )
    )

    assert commute_point is None
    assert len(result.properties) == 1
    assert result.properties[0].is_approximate is True
    assert "僅定位至文山區代表點" in result.properties[0].address
    assert any("行政區約略位置" in warning for warning in result.warnings)


def test_street_fallback_keeps_district_for_numbered_alley():
    cleaned = map_service._clean_listing_address(
        "地址：台北市 文山區 指南路三段22巷1弄5號3樓"
    )

    assert cleaned == "指南路三段22巷1弄5號, 文山區"
    assert (
        map_service._street_level_address(cleaned)
        == "指南路三段, 文山區"
    )


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
