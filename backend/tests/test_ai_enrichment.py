from types import SimpleNamespace
import pytest

from app.agents import ai_enrichment
from app.agents.ai_enrichment import (
    CostEstimateBatch,
    CostEstimateItem,
    ListingRequirementBatch,
    ListingRequirementCheckItem,
    ListingRequirementItem,
    ListingUseBatch,
    ListingUseItem,
    PropertyVisionBatch,
    PropertyVisionItem,
    analyze_property_images,
    apply_cost_estimate,
    apply_listing_requirement_analysis,
    apply_property_vision,
    classify_listing_uses,
    estimate_property_costs,
    interpret_listing_requirements,
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


@pytest.mark.parametrize("bundled", [False, True])
def test_property_agent_sends_image_and_never_treats_unseen_window_as_no_window(
    monkeypatch, bundled,
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
            if bundled:
                images = [item for item in content if item["type"] == "input_image"]
                assert len(images) == 1
                assert images[0]["image_url"].startswith("data:image/jpeg;base64,")
            return SimpleNamespace(output_parsed=parsed)

    class FakeOpenAI:
        def __init__(self, api_key):
            self.responses = FakeResponses()

    monkeypatch.setattr(ai_enrichment, "get_settings", _mock_settings)
    monkeypatch.setattr(ai_enrichment, "OpenAI", FakeOpenAI)
    property_ = _property()
    if bundled:
        property_.image_url = "/listing-photos/01-bright-studio-window.jpg"
        property_.image_urls = [property_.image_url]
    analyses, _ = analyze_property_images([property_])
    enriched = apply_property_vision(property_, analyses[property_.id])

    assert enriched.has_window is None
    assert enriched.vision_analyzed_by_ai is True
    assert enriched.vision_window_visible is False
    assert enriched.space_impression == "compact"
    assert enriched.vision_confidence == "low"


def test_property_agent_semantically_interprets_full_listing_text(monkeypatch):
    parsed = ListingRequirementBatch(
        analyses=[
            ListingRequirementItem(
                property_id="listing-1",
                summary="刊登明確禁寵、接受租補，並表示環境安靜。",
                checks=[
                    ListingRequirementCheckItem(
                        label="可養貓",
                        status="unmet",
                        evidence="房東註明謝絕毛小孩",
                        confidence="high",
                    ),
                    ListingRequirementCheckItem(
                        label="租金補貼",
                        status="met",
                        evidence="可協助申請中央租金補貼",
                        confidence="high",
                    ),
                ],
                noise_assessment_performed=True,
                noise_level="low",
                noise_evidence="原文寫「住宅巷內，夜間環境安靜」",
                noise_confidence="high",
            )
        ]
    )

    class FakeResponses:
        def parse(self, **kwargs):
            assert kwargs["text_format"] is ListingRequirementBatch
            assert "web_search" not in str(kwargs.get("tools", ""))
            assert "謝絕毛小孩" in kwargs["input"]
            return SimpleNamespace(output_parsed=parsed)

    class FakeOpenAI:
        def __init__(self, api_key):
            self.responses = FakeResponses()

    monkeypatch.setattr(ai_enrichment, "get_settings", _mock_settings)
    monkeypatch.setattr(ai_enrichment, "OpenAI", FakeOpenAI)
    property_ = _property(
        listing_text=(
            "房東註明謝絕毛小孩，但可協助申請中央租金補貼。"
            "住宅巷內，夜間環境安靜。"
        ),
        listing_text_source="detail_page",
    )
    requirements = UserRequirements(
        needs_window=False,
        needs_rental_subsidy=True,
        preferences=["可養貓"],
    )

    analyses, _ = interpret_listing_requirements(requirements, [property_])
    enriched = apply_listing_requirement_analysis(
        property_,
        analyses[property_.id],
    )

    assert enriched.listing_requirements_analyzed_by_ai is True
    assert enriched.rental_subsidy_eligible is True
    assert enriched.noise_analyzed_by_ai is True
    assert enriched.noise_level == "low"
    assert enriched.noise_confidence == "high"
    assert "夜間環境安靜" in enriched.noise_evidence
    assert next(
        check for check in enriched.listing_requirement_checks
        if check.label == "可養貓"
    ).status == "unmet"


def test_property_noise_ai_does_not_guess_without_reliable_evidence():
    property_ = _property(noise_level="low")
    analysis = ListingRequirementItem(
        property_id="listing-1",
        summary="刊登沒有提供可核對的安靜程度資訊。",
        checks=[],
        noise_assessment_performed=True,
        noise_level="unknown",
        noise_evidence="刊登未提及噪音環境",
        noise_confidence="low",
    )

    enriched = apply_listing_requirement_analysis(property_, analysis)

    assert enriched.noise_level == "low"
    assert enriched.noise_analyzed_by_ai is True
    assert enriched.noise_confidence == "low"


def test_ai_classifies_storage_listing_as_not_habitable(monkeypatch):
    parsed = ListingUseBatch(
        analyses=[
            ListingUseItem(
                property_id="listing-1",
                classification="not_habitable",
                property_type="置物空間",
                evidence="僅供堆放攝影器材，禁止居住及過夜",
                confidence="high",
            )
        ]
    )

    class FakeResponses:
        def parse(self, **kwargs):
            assert kwargs["text_format"] is ListingUseBatch
            assert "禁止居住及過夜" in kwargs["input"]
            return SimpleNamespace(output_parsed=parsed)

    class FakeOpenAI:
        def __init__(self, api_key):
            self.responses = FakeResponses()

    monkeypatch.setattr(ai_enrichment, "get_settings", _mock_settings)
    monkeypatch.setattr(ai_enrichment, "OpenAI", FakeOpenAI)
    analyses, message = classify_listing_uses(
        [
            _property(
                title="攝影工作空間",
                listing_text="僅供堆放攝影器材，禁止居住及過夜。",
                listing_text_source="detail_page",
            )
        ]
    )

    assert analyses["listing-1"].classification == "not_habitable"
    assert "排除 1 筆" in message
