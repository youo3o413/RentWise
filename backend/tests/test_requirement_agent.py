from types import SimpleNamespace

from app.agents import requirement_agent
from app.agents.requirement_agent import (
    ParsedRequirementIntent,
    ParsedWeights,
    merge_requirement_intent,
    parse_natural_language_requirements,
)
from app.models.schemas import UserRequirements


def test_merge_intent_preserves_unspecified_form_values():
    current = UserRequirements(
        budget=15000,
        destination="政治大學",
        needs_elevator=False,
        preferences=["採光良好"],
        property_source="591",
    )
    intent = ParsedRequirementIntent(
        destination="輔仁大學",
        max_commute_minutes=30,
        needs_window=True,
        weights=ParsedWeights(location=60, cost=20),
        interpretation="改為輔大通勤需求。",
    )

    result = merge_requirement_intent(current, intent)

    assert result.destination == "輔仁大學"
    assert result.budget == 15000
    assert result.max_commute_minutes == 30
    assert result.needs_elevator is False
    assert result.preferences == ["採光良好"]
    assert result.weights.location == 60
    assert result.weights.cost == 20
    assert result.weights.property == 40
    assert result.property_source == "591"


def test_requirement_agent_uses_structured_response(monkeypatch):
    parsed = ParsedRequirementIntent(
        budget=16000,
        destination="台灣大學",
        needs_convenience_store=True,
        interpretation="台大附近、預算一萬六且需要超商。",
        assumptions=["通勤時間沿用目前設定"],
    )

    class FakeResponses:
        def parse(self, **kwargs):
            assert kwargs["text_format"] is ParsedRequirementIntent
            assert kwargs["input"] == "台大附近一萬六，要有超商"
            return SimpleNamespace(output_parsed=parsed)

    class FakeOpenAI:
        def __init__(self, api_key):
            assert api_key == "test-key"
            self.responses = FakeResponses()

    monkeypatch.setattr(
        requirement_agent,
        "get_settings",
        lambda: SimpleNamespace(
            openai_api_key="test-key",
            openai_model="gpt-4.1-mini",
        ),
    )
    monkeypatch.setattr(requirement_agent, "OpenAI", FakeOpenAI)

    result = parse_natural_language_requirements(
        "台大附近一萬六，要有超商",
        UserRequirements(property_source="591"),
    )

    assert result.mode == "ai"
    assert result.requirements.destination == "台灣大學"
    assert result.requirements.budget == 16000
    assert result.requirements.needs_convenience_store is True
    assert result.assumptions == ["通勤時間沿用目前設定"]
    assert result.updated_fields == [
        "budget",
        "destination",
        "needs_convenience_store",
    ]
