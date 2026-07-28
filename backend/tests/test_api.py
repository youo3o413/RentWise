from fastapi.testclient import TestClient
from app.models.schemas import (
    DestinationResolveResponse,
    RequirementParseResponse,
    UserRequirements,
)
from app.agents.requirement_agent import RequirementAgentQuotaError
from app.graph import rentwise_graph as graph_module
from app import main as main_module
from app.main import app

client = TestClient(app)


def test_health():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_recommendation_returns_ranked_live_properties(monkeypatch):
    def fake_invoke(state, config=None):
        assert state["requirements"].property_source == "multi"
        assert state["requirements"].destination == "台灣大學"
        assert state["trace"][0].agent == "Requirement Agent"
        assert "LangGraph 前" in state["trace"][0].message
        assert config["configurable"]["thread_id"]
        assessment = {
            "agent": "Test Agent",
            "property_id": "listing-1",
            "score": 80,
            "summary": "測試分析",
            "positives": [],
            "concerns": [],
            "metrics": {},
            "checks": [],
        }
        return {
            "requirements": state["requirements"],
            "mode": "rules",
            "summary": "測試決策說明",
            "ranked_results": [
                {
                    "rank": 1,
                    "property": {
                        "id": "listing-1",
                        "title": "即時房源",
                        "address": "台北市文山區",
                        "rent": 12000,
                        "management_fee": 0,
                        "water_fee": 0,
                        "electricity_rate": 5,
                        "estimated_kwh": 100,
                        "commute_minutes": 20,
                        "has_window": True,
                        "window_type": "對外窗",
                        "has_elevator": None,
                        "floor": 2,
                        "noise_level": None,
                        "nearby": [],
                        "features": [],
                        "risks": [],
                        "description": "",
                        "image_url": "https://example.com/listing.jpg",
                        "source_name": "591租屋",
                    },
                    "total_score": 80,
                    "estimated_monthly_cost": 12500,
                    "recommendation": "建議比較後看房。",
                    "strengths": [],
                    "tradeoffs": [],
                    "assessments": {
                        "location": assessment,
                        "cost": assessment,
                        "property": assessment,
                        "suitability": assessment,
                    },
                }
            ],
            "trace": [
                {
                    "agent": "Source Planning Agent",
                    "status": "completed",
                    "message": "已完成即時來源規劃",
                    "property_count": 1,
                }
            ],
        }

    monkeypatch.setattr(
        main_module,
        "parse_natural_language_requirements",
        lambda text, current: RequirementParseResponse(
            requirements=current.model_copy(
                update={"destination": "台灣大學"}
            ),
            interpretation="已將目的地解析為台灣大學。",
            updated_fields=["destination"],
            assumptions=[],
            mode="ai",
        ),
    )
    monkeypatch.setattr(
        main_module.rentwise_graph,
        "invoke",
        fake_invoke,
    )
    response = client.post(
        "/api/recommend",
        json={
            "budget": 15000,
            "destination": "政治大學",
            "requirement_text": "我在台大上課",
            "requirements_parsed": False,
            "max_commute_minutes": 25,
            "needs_window": True,
            "noise_preference": "quiet",
            "needs_elevator": False,
            "needs_convenience_store": True,
            "max_floor_without_elevator": 3,
            "preferences": ["採光良好", "可開伙"],
            "weights": {
                "location": 40,
                "cost": 30,
                "property": 30,
            },
            "property_source": "multi",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["results"]) == 1
    assert body["property_source"] == "multi"
    assert body["mode"] == "rules"
    assert body["results"][0]["rank"] == 1
    assert body["current_weights"] == {
        "location": 40,
        "cost": 30,
        "property": 30,
    }
    assert body["trace"][0]["agent"] == "Source Planning Agent"
    assert body["trace"][0]["status"] == "completed"


def test_removed_demo_property_source_is_rejected():
    response = client.post(
        "/api/recommend",
        json={
            "destination": "政治大學",
            "property_source": "demo",
        },
    )

    assert response.status_code == 422


def test_parse_requirements_endpoint(monkeypatch):
    def fake_parse(text, current):
        assert text == "輔大附近，通勤最重要"
        return RequirementParseResponse(
            requirements=current.model_copy(
                update={"destination": "輔仁大學"}
            ),
            interpretation="目的地改為輔仁大學並提高通勤權重。",
            assumptions=[],
            mode="ai",
        )

    monkeypatch.setattr(
        main_module,
        "parse_natural_language_requirements",
        fake_parse,
    )
    response = client.post(
        "/api/parse-requirements",
        json={
            "text": "輔大附近，通勤最重要",
            "current": UserRequirements(property_source="591").model_dump(),
        },
    )

    assert response.status_code == 200
    assert response.json()["requirements"]["destination"] == "輔仁大學"
    assert response.json()["mode"] == "ai"


def test_parse_requirements_reports_openai_quota(monkeypatch):
    def fake_parse(text, current):
        raise RequirementAgentQuotaError(
            "OpenAI API 額度不足。請到 API Billing 加值，"
            "等待額度更新後再試。"
        )

    monkeypatch.setattr(
        main_module,
        "parse_natural_language_requirements",
        fake_parse,
    )
    response = client.post(
        "/api/parse-requirements",
        json={"text": "台大附近，要可以養貓"},
    )

    assert response.status_code == 429
    assert "API Billing" in response.json()["detail"]


def test_resolve_destination_endpoint_returns_concrete_location(monkeypatch):
    monkeypatch.setattr(
        main_module,
        "resolve_destination",
        lambda query: DestinationResolveResponse(
            query=query,
            resolved_label="新北市 · 新店區 · Yes!Life裕隆城",
            resolved_address="Yes!Life裕隆城, 新店區, 新北市, 台灣",
            region_name="新北市",
            district_name="新店區",
            latitude=24.9781,
            longitude=121.5468,
            source="openstreetmap",
            confidence="high",
        ),
    )

    response = client.post(
        "/api/resolve-destination",
        json={"query": "裕隆城"},
    )

    assert response.status_code == 200
    assert response.json()["district_name"] == "新店區"
    assert response.json()["latitude"] == 24.9781
