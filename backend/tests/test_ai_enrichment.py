from types import SimpleNamespace

from app.agents import ai_enrichment
from app.agents.ai_enrichment import (
    CostEstimateBatch,
    CostEstimateItem,
    PropertyVisionBatch,
    PropertyVisionItem,
    analyze_property_images,
    apply_cost_estimate,
    apply_property_vision,
    estimate_property_costs,
)
from app.models.schemas import Property, UserRequirements


def _property(**updates) -> Property:
    values = {
        "id": "listing-1",
        "title": "新店九坪套房",
        "address": "新北市新店區寶橋路",
        "rent": 15000,
        "management_fee": 0,
        "water_fee": 0,
        "electricity_rate": 5,
        "estimated_kwh": 100,
        "management_fee_disclosed": False,
        "water_fee_disclosed": False,
        "electricity_rate_disclosed": False,
        "electricity_usage_disclosed": False,
        "commute_minutes": 10,
        "has_window": None,
        "window_type": "未揭露",
        "has_elevator": None,
        "floor": 3,
        "noise_level": None,
        "nearby": [],
        "listing_area_ping": 9,
        "features": ["9坪"],
        "risks": [],
        "description": "",
        "image_url": "https://example.com/listing.jpg",
    }
    values.update(updates)
    return Property(**values)


def _mock_settings():
    return SimpleNamespace(
        openai_api_key="test-key",
        openai_model="gpt-4.1-mini",
    )


def test_cost_agent_uses_structured_ai_and_only_fills_missing_values(monkeypatch):
    parsed = CostEstimateBatch(
        estimates=[
            CostEstimateItem(
                property_id="listing-1",
                management_fee=600,
                water_fee=180,
                electricity_rate=5.2,
                estimated_kwh=120,
                confidence="medium",
                basis=["新店區一般住宅用電情境", "九坪套房單人居住"],
            )
        ]
    )

    class FakeResponses:
        def parse(self, **kwargs):
            assert kwargs["text_format"] is CostEstimateBatch
            assert kwargs["tools"][0]["type"] == "web_search"
            return SimpleNamespace(output_parsed=parsed)

    class FakeOpenAI:
        def __init__(self, api_key):
            assert api_key == "test-key"
            self.responses = FakeResponses()

    monkeypatch.setattr(ai_enrichment, "get_settings", _mock_settings)
    monkeypatch.setattr(ai_enrichment, "OpenAI", FakeOpenAI)
    property_ = _property(management_fee=900, management_fee_disclosed=True)
    estimates, _ = estimate_property_costs(
        UserRequirements(destination="裕隆城"),
        [property_],
    )
    enriched = apply_cost_estimate(property_, estimates[property_.id])

    assert enriched.management_fee == 900
    assert enriched.water_fee == 180
    assert enriched.electricity_rate == 5.2
    assert enriched.estimated_kwh == 120
    assert enriched.cost_estimated_by_ai is True


def test_property_agent_sends_image_and_never_treats_unseen_window_as_no_window(
    monkeypatch,
):
    parsed = PropertyVisionBatch(
        analyses=[
            PropertyVisionItem(
                property_id="listing-1",
                visible_window=False,
                window_description="照片沒有清楚拍到窗戶",
                space_impression="compact",
                summary="依九坪刊登資訊與單張照片，動線可能較緊湊。",
                confidence="low",
            )
        ]
    )

    class FakeResponses:
        def parse(self, **kwargs):
            assert kwargs["text_format"] is PropertyVisionBatch
            content = kwargs["input"][0]["content"]
            assert any(item["type"] == "input_image" for item in content)
            return SimpleNamespace(output_parsed=parsed)

    class FakeOpenAI:
        def __init__(self, api_key):
            self.responses = FakeResponses()

    monkeypatch.setattr(ai_enrichment, "get_settings", _mock_settings)
    monkeypatch.setattr(ai_enrichment, "OpenAI", FakeOpenAI)
    property_ = _property()
    analyses, _ = analyze_property_images([property_])
    enriched = apply_property_vision(property_, analyses[property_.id])

    assert enriched.has_window is None
    assert enriched.vision_analyzed_by_ai is True
    assert enriched.vision_window_visible is False
    assert enriched.space_impression == "compact"
    assert enriched.vision_confidence == "low"
