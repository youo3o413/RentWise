from uuid import uuid4

from langgraph.types import Command

from app.graph import rentwise_graph as graph_module
from app.models.schemas import Property, UserRequirements
from app.services.source_planning_service import SourceSearchPlan


def _property(index: int) -> Property:
    return Property(
        id=f"listing-{index}",
        title=f"測試房源 {index}",
        address="台北市文山區指南路",
        rent=10000 + index * 500,
        management_fee=0,
        water_fee=0,
        electricity_rate=5,
        estimated_kwh=100,
        commute_minutes=10 + index,
        commute_method="測試步行路網",
        has_window=True,
        window_type="對外窗",
        has_elevator=True,
        floor=2,
        noise_level="low",
        nearby=["便利商店"],
        nearby_convenience_store_count=1,
        nearest_convenience_store_meters=100,
        features=[],
        risks=[],
        description="測試房源",
        image_url="https://example.com/property.jpg",
    )


def _stub_external_analysis(monkeypatch):
    properties = [_property(index) for index in range(1, 5)]
    monkeypatch.setattr(
        graph_module,
        "build_source_search_plan",
        lambda req: SourceSearchPlan(
            destination=req.destination,
            region_name="台北市",
            keywords=(req.destination,),
            sources=("591租屋",),
            resolved_address="台北市文山區",
            latitude=24.98,
            longitude=121.57,
        ),
    )
    monkeypatch.setattr(
        graph_module,
        "load_properties_for_requirements",
        lambda req, plan: properties,
    )
    monkeypatch.setattr(
        graph_module,
        "classify_listing_uses",
        lambda items: ({}, "規則分類完成"),
    )
    monkeypatch.setattr(
        graph_module,
        "enrich_commute_data",
        lambda items, *args: items,
    )
    monkeypatch.setattr(
        graph_module,
        "estimate_property_costs",
        lambda req, items: ({}, "成本資料完整"),
    )
    monkeypatch.setattr(
        graph_module,
        "interpret_listing_requirements",
        lambda req, items: ({}, "刊登語意完成"),
    )
    monkeypatch.setattr(
        graph_module,
        "analyze_property_images",
        lambda items: ({}, "圖片分析完成"),
    )
    monkeypatch.setattr(
        graph_module,
        "generate_decision_explanation",
        lambda req, ranked, context: ("測試決策摘要", "rules"),
    )


def test_graph_runs_parallel_agents_and_finishes_when_auto_accepted(monkeypatch):
    _stub_external_analysis(monkeypatch)
    thread_id = str(uuid4())
    result = graph_module.rentwise_graph.invoke(
        {
            "requirements": UserRequirements(),
            "minimum_properties": 4,
            "auto_accept": True,
            "trace": [],
        },
        config={"configurable": {"thread_id": thread_id}},
    )

    assert "__interrupt__" not in result
    assert len(result["ranked_results"]) == 4
    agents = {item.agent for item in result["trace"]}
    assert {
        "Data Loader",
        "Location Agent",
        "Location Agent Tools",
        "Cost Agent",
        "Property Agent",
        "Parallel Analysis Join",
        "Decision Explanation Agent",
    } <= agents


def test_graph_pauses_for_feedback_and_reranks_without_research(monkeypatch):
    _stub_external_analysis(monkeypatch)
    thread_id = str(uuid4())
    config = {"configurable": {"thread_id": thread_id}}
    initial = graph_module.rentwise_graph.invoke(
        {
            "requirements": UserRequirements(),
            "minimum_properties": 4,
            "auto_accept": False,
            "trace": [],
        },
        config=config,
    )

    assert initial["__interrupt__"]
    reloaded_graph = graph_module.build_graph()
    restored = reloaded_graph.get_state(config)
    assert restored.values["ranked_results"][0]["rank"] == 1
    assert restored.interrupts
    resumed = graph_module.rentwise_graph.invoke(
        Command(
            resume={
                "accepted": False,
                "weights": {
                    "location": 10,
                    "cost": 60,
                    "property": 30,
                },
            }
        ),
        config=config,
    )

    assert resumed["__interrupt__"]
    assert resumed["requirements"].weights.cost == 60
    assert sum(
        item.agent == "Data Loader"
        for item in resumed["trace"]
    ) == 1
    assert any(item.agent == "Human Feedback" for item in resumed["trace"])

    completed = graph_module.rentwise_graph.invoke(
        Command(resume={"accepted": True}),
        config=config,
    )
    assert "__interrupt__" not in completed
    assert completed["recommendation_accepted"] is True
