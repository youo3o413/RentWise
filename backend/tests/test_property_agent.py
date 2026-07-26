from app.agents.rule_agents import (
    cost_assessment,
    location_assessment,
    property_assessment,
    suitability_assessment,
)
from app.models.schemas import (
    AgentAssessment,
    Property,
    SuitabilityWeights,
    UserRequirements,
)


def _property(**updates) -> Property:
    values = {
        "id": "listing-1",
        "title": "採光套房",
        "address": "文山區指南路",
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
        "features": ["採光良好"],
        "risks": [],
        "description": "房間明亮",
        "image_url": "https://example.com/image.jpg",
    }
    values.update(updates)
    return Property(**values)


def test_property_agent_returns_explicit_condition_checks():
    requirements = UserRequirements(
        needs_window=True,
        needs_elevator=True,
        max_floor_without_elevator=3,
        preferences=["採光良好", "可開伙"],
        property_source="demo",
    )

    result = property_assessment(_property(), requirements)
    checks = {check.label: check for check in result.checks}

    assert checks["對外窗"].status == "met"
    assert checks["電梯"].status == "unknown"
    assert checks["樓層負擔"].status == "met"
    assert checks["採光良好"].status == "met"
    assert checks["可開伙"].status == "unknown"
    assert result.metrics["met_count"] == 3
    assert result.metrics["unknown_count"] == 2
    assert result.metrics["unmet_count"] == 0
    assert result.metrics["data_completeness"] == 60
    assert result.metrics["known_match_rate"] == 100
    assert result.score == 100
    assert result.metrics["score_available"] is True


def test_property_agent_marks_confirmed_conflicts():
    requirements = UserRequirements(
        needs_window=True,
        needs_elevator=True,
        max_floor_without_elevator=3,
        preferences=[],
        property_source="demo",
    )

    result = property_assessment(
        _property(has_window=False, has_elevator=False, floor=5),
        requirements,
    )

    assert result.metrics["unmet_count"] == 3
    assert result.metrics["unknown_count"] == 0
    assert result.score == 0


def test_property_agent_treats_all_unknown_as_neutral():
    requirements = UserRequirements(
        needs_window=True,
        needs_elevator=True,
        preferences=["可開伙"],
        property_source="demo",
    )

    result = property_assessment(
        _property(
            has_window=None,
            has_elevator=None,
            floor=None,
            title="一般套房",
            features=[],
            description="",
        ),
        requirements,
    )

    assert result.metrics["data_completeness"] == 0
    assert result.metrics["unknown_count"] == 4
    assert result.score == 0
    assert result.metrics["score_available"] is False


def _assessment(
    agent: str,
    score: float,
    metrics: dict | None = None,
) -> AgentAssessment:
    return AgentAssessment(
        agent=agent,
        property_id="listing-1",
        score=score,
        summary="",
        positives=[],
        concerns=[],
        metrics=metrics or {},
    )


def test_suitability_uses_user_defined_weights():
    property_ = _property(noise_level=None)
    requirements = UserRequirements(
        needs_window=False,
        weights=SuitabilityWeights(
            location=70,
            cost=20,
            property=10,
            noise=0,
        ),
        property_source="demo",
    )

    result = suitability_assessment(
        property_,
        requirements,
        _assessment("Location Agent", 100),
        _assessment("Cost Agent", 50),
        _assessment("Property Agent", 80),
    )

    assert result.score == 88
    assert result.metrics["location_weight"] == 0.7
    assert result.metrics["cost_weight"] == 0.2


def test_property_agent_does_not_misread_no_pets_as_pet_friendly():
    requirements = UserRequirements(
        needs_window=False,
        preferences=["可養貓"],
        property_source="demo",
    )

    result = property_assessment(
        _property(
            title="安靜套房",
            features=[],
            description="房東規定不可養寵物",
        ),
        requirements,
    )
    check = next(check for check in result.checks if check.label == "可養貓")

    assert check.status == "unmet"
    assert "不符合" in check.evidence


def test_rental_subsidy_is_visible_and_explicit_conflict_affects_suitability():
    requirements = UserRequirements(
        needs_window=False,
        needs_rental_subsidy=True,
        property_source="demo",
    )
    property_ = _property(rental_subsidy_eligible=False)
    property_result = property_assessment(property_, requirements)
    subsidy = next(
        check for check in property_result.checks if check.label == "租金補貼"
    )

    assert subsidy.status == "unmet"
    result = suitability_assessment(
        property_,
        requirements,
        _assessment("Location Agent", 80),
        _assessment("Cost Agent", 80),
        property_result,
    )
    assert result.metrics["qualified"] is False
    assert result.metrics["disqualifying_conflicts"] == "租金補貼"
    assert any("租金補貼" in concern for concern in result.concerns)


def test_unrevealed_rental_subsidy_is_unknown_not_rejected():
    result = property_assessment(
        _property(rental_subsidy_eligible=None),
        UserRequirements(
            needs_window=False,
            needs_rental_subsidy=True,
            property_source="demo",
        ),
    )
    subsidy = next(check for check in result.checks if check.label == "租金補貼")

    assert subsidy.status == "unknown"


def test_location_score_uses_commute_ratio_instead_of_starting_at_100():
    requirements = UserRequirements(
        max_commute_minutes=25,
        needs_convenience_store=False,
        property_source="demo",
    )

    assert location_assessment(
        _property(commute_minutes=15),
        requirements,
    ).score == 100
    assert location_assessment(
        _property(commute_minutes=25),
        requirements,
    ).score == 70
    assert location_assessment(
        _property(commute_minutes=30),
        requirements,
    ).score == 50


def test_location_splits_commute_and_store_only_when_store_is_requested():
    property_ = _property(
        commute_minutes=25,
        nearby_convenience_store_count=1,
        nearest_convenience_store_meters=100,
    )

    with_store = location_assessment(
        property_,
        UserRequirements(
            max_commute_minutes=25,
            needs_convenience_store=True,
            property_source="demo",
        ),
    )
    without_store = location_assessment(
        property_,
        UserRequirements(
            max_commute_minutes=25,
            needs_convenience_store=False,
            property_source="demo",
        ),
    )

    assert with_store.score == 85
    assert with_store.metrics["commute_component_weight"] == 0.5
    assert with_store.metrics["store_component_weight"] == 0.5
    assert without_store.score == 70
    assert without_store.metrics["commute_component_weight"] == 1
    assert without_store.metrics["store_component_weight"] == 0


def test_cost_score_uses_monthly_cost_to_budget_ratio():
    requirements = UserRequirements(budget=15000, property_source="demo")

    assert cost_assessment(
        _property(rent=10000, electricity_rate=5, estimated_kwh=100),
        requirements,
    ).score == 100
    assert cost_assessment(
        _property(rent=14500, electricity_rate=5, estimated_kwh=100),
        requirements,
    ).score == 70


def test_suitability_redistributes_unknown_dimensions_without_neutral_score():
    property_ = _property(noise_level=None)
    requirements = UserRequirements(
        needs_window=False,
        weights=SuitabilityWeights(
            location=40,
            cost=30,
            property=20,
            noise=10,
        ),
        property_source="demo",
    )

    result = suitability_assessment(
        property_,
        requirements,
        _assessment("Location Agent", 100, {"score_available": True}),
        _assessment("Cost Agent", 50, {"score_available": True}),
        _assessment("Property Agent", 0, {"score_available": False}),
    )

    assert result.score == 78.6
    assert result.metrics["location_weight"] == 0.571
    assert result.metrics["cost_weight"] == 0.429
    assert result.metrics["property_weight"] == 0
    assert result.metrics["noise_weight"] == 0
    assert result.metrics["evidence_coverage_percent"] == 70
