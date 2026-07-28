from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from app.agents.decision_explanation import generate_decision_explanation
from app.agents.ai_enrichment import (
    analyze_property_images,
    apply_cost_estimate,
    apply_listing_requirement_analysis,
    apply_property_vision,
    classify_listing_uses,
    estimate_property_costs,
    interpret_listing_requirements,
)
from app.agents.rule_agents import (
    cost_assessment,
    location_assessment,
    property_assessment,
    suitability_assessment,
)
from app.models.schemas import AgentTrace, Property, UserRequirements
from app.services.property_service import load_properties_for_requirements
from app.services.rent591_service import Rent591Error
from app.services.commute_service import enrich_commute_data
from app.services.source_planning_service import (
    SourceSearchPlan,
    build_source_search_plan,
)


class RentWiseState(TypedDict, total=False):
    requirements: UserRequirements
    source_plan: SourceSearchPlan
    properties: list[Property]
    location_results: dict[str, Any]
    cost_results: dict[str, Any]
    property_results: dict[str, Any]
    suitability_results: dict[str, Any]
    ranked_results: list[dict[str, Any]]
    summary: str
    mode: str
    trace: list[AgentTrace]


def source_planning_node(state: RentWiseState) -> dict:
    req = state["requirements"]
    plan = build_source_search_plan(req)
    return {
        "source_plan": plan,
        "trace": [
            AgentTrace(
                agent="Source Planning Agent",
                status="completed",
                message=(
                    f"已將「{req.destination}」定位為 {plan.region_name} "
                    f"生活圈"
                    + (
                        f"（{plan.resolved_address}）"
                        if plan.resolved_address != plan.destination
                        else ""
                    )
                    + f"，搜尋 {'、'.join(plan.sources)}"
                ),
                property_count=0,
            )
        ],
    }


def load_node(state: RentWiseState) -> dict:
    req = state["requirements"]
    properties = load_properties_for_requirements(
        req,
        state.get("source_plan"),
    )
    original_count = len(properties)
    use_analyses, use_message = classify_listing_uses(properties)
    properties = [
        property_
        for property_ in properties
        if not (
            (analysis := use_analyses.get(property_.id))
            and analysis.classification == "not_habitable"
            and analysis.confidence in {"medium", "high"}
        )
    ]
    if original_count and not properties:
        raise Rent591Error("取得的刊登皆為車位、置物空間或其他非住宅用途。")
    source_label = {
        "multi": "多平台即時",
        "591": "591 即時",
    }[req.property_source]
    return {
        "properties": properties,
        "trace": state["trace"] + [
            AgentTrace(
                agent="Data Loader",
                status="completed",
                message=(
                    f"已載入 {len(properties)} 筆{source_label}可居住候選房源"
                    f"；{use_message}"
                ),
                property_count=len(properties),
            )
        ],
    }


def location_node(state: RentWiseState) -> dict:
    req = state["requirements"]
    plan = state.get("source_plan")
    destination_coordinates = (
        (plan.latitude, plan.longitude)
        if plan and plan.latitude is not None and plan.longitude is not None
        else (
            (req.destination_latitude, req.destination_longitude)
            if req.destination_latitude is not None
            and req.destination_longitude is not None
            else None
        )
    )
    properties = enrich_commute_data(
        state["properties"],
        (
            plan.resolved_address
            if plan and plan.resolved_address
            else req.destination_resolved_address or req.destination
        ),
        req.commute_mode,
        req.needs_parking,
        destination_coordinates,
    )
    results = {p.id: location_assessment(p, req) for p in properties}
    commute_count = sum(p.commute_minutes is not None for p in properties)
    transit_count = sum(
        p.commute_method == "TDX 大眾運輸＋步行" for p in properties
    )
    driving_count = sum(
        p.commute_method == "Valhalla 駕車路網" for p in properties
    )
    walking_count = commute_count - transit_count - driving_count
    return {
        "properties": properties,
        "location_results": results,
        "trace": state["trace"] + [
            AgentTrace(
                agent="Location Agent",
                status="completed",
                message=(
                    f"已計算 {transit_count} 筆大眾運輸、"
                    f"{walking_count} 筆步行、{driving_count} 筆駕車通勤"
                    "並完成生活機能分析"
                ),
                property_count=len(results),
            )
        ],
    }


def cost_node(state: RentWiseState) -> dict:
    req = state["requirements"]
    estimates, message = estimate_property_costs(req, state["properties"])
    properties = [
        apply_cost_estimate(p, estimates.get(p.id))
        for p in state["properties"]
    ]
    results = {p.id: cost_assessment(p, req) for p in properties}
    return {
        "properties": properties,
        "cost_results": results,
        "trace": state["trace"] + [
            AgentTrace(
                agent="Cost Agent",
                status="completed",
                message=message,
                property_count=len(results),
            )
        ],
    }


def property_node(state: RentWiseState) -> dict:
    req = state["requirements"]
    requirement_analyses, requirement_message = interpret_listing_requirements(
        req,
        state["properties"],
    )
    interpreted_properties = [
        apply_listing_requirement_analysis(
            property_,
            requirement_analyses.get(property_.id),
        )
        for property_ in state["properties"]
    ]
    analyses, vision_message = analyze_property_images(interpreted_properties)
    properties = [
        apply_property_vision(p, analyses.get(p.id))
        for p in interpreted_properties
    ]
    results = {p.id: property_assessment(p, req) for p in properties}
    return {
        "properties": properties,
        "property_results": results,
        "trace": state["trace"] + [
            AgentTrace(
                agent="Property Agent",
                status="completed",
                message=f"{requirement_message}；{vision_message}",
                property_count=len(results),
            )
        ],
    }


def suitability_node(state: RentWiseState) -> dict:
    req = state["requirements"]
    results = {}
    for p in state["properties"]:
        results[p.id] = suitability_assessment(
            p,
            req,
            state["location_results"][p.id],
            state["cost_results"][p.id],
            state["property_results"][p.id],
        )
    return {
        "suitability_results": results,
        "trace": state["trace"] + [
            AgentTrace(
                agent="Suitability Agent",
                status="completed",
                message="已依個人偏好完成加權適配評估",
                property_count=len(results),
            )
        ],
    }


def decision_explanation_node(state: RentWiseState) -> dict:
    ranked = []
    for p in state["properties"]:
        assessments = {
            "location": state["location_results"][p.id],
            "cost": state["cost_results"][p.id],
            "property": state["property_results"][p.id],
            "suitability": state["suitability_results"][p.id],
        }
        strengths = []
        tradeoffs = []
        for assessment in assessments.values():
            strengths.extend(assessment.positives)
            tradeoffs.extend(assessment.concerns)

        total_score = state["suitability_results"][p.id].score
        ranked.append(
            {
                "property": p,
                "total_score": total_score,
                "estimated_monthly_cost": state["cost_results"][p.id].metrics[
                    "estimated_monthly_cost"
                ],
                "strengths": list(dict.fromkeys(strengths))[:5],
                "tradeoffs": list(dict.fromkeys(tradeoffs))[:5],
                "assessments": assessments,
            }
        )

    ranked.sort(
        key=lambda item: (
            bool(
                item["assessments"]["suitability"].metrics.get(
                    "qualified",
                    True,
                )
            ),
            item["total_score"],
            item["assessments"]["property"].metrics.get(
                "data_completeness",
                0,
            ),
        ),
        reverse=True,
    )
    for index, item in enumerate(ranked, start=1):
        item["rank"] = index
        qualified = bool(
            item["assessments"]["suitability"].metrics.get(
                "qualified",
                True,
            )
        )
        if not qualified:
            conflicts = item["assessments"]["suitability"].metrics.get(
                "disqualifying_conflicts",
                "必要條件",
            )
            item["recommendation"] = (
                f"不符合必要條件（{conflicts}），不建議列為合格候選。"
            )
        elif index == 1:
            item["recommendation"] = "最符合目前需求，建議優先安排看房。"
        elif item["total_score"] >= 75:
            item["recommendation"] = "整體條件不錯，可作為備選並比較實際房況。"
        else:
            item["recommendation"] = "存在明顯取捨，除非願意調整需求，否則不優先。"

    plan = state.get("source_plan")
    destination_context = (
        f"{plan.destination}；地理定位：{plan.resolved_address}；"
        f"縣市生活圈：{plan.region_name}"
        if plan
        else state["requirements"].destination
    )
    summary, mode = generate_decision_explanation(
        state["requirements"],
        ranked,
        destination_context,
    )
    return {
        "ranked_results": ranked,
        "summary": summary,
        "mode": mode,
        "trace": state["trace"] + [
            AgentTrace(
                agent="Decision Explanation Agent",
                status="completed",
                message=(
                    "OpenAI 已整合所有 Agent、目的地脈絡與不確定性"
                    if mode == "ai"
                    else "OpenAI 暫時無法使用，已用透明規則完成排名摘要"
                ),
                property_count=len(ranked),
            )
        ],
    }


def build_graph():
    graph = StateGraph(RentWiseState)
    graph.add_node("source_planning_agent", source_planning_node)
    graph.add_node("load_properties", load_node)
    graph.add_node("location_agent", location_node)
    graph.add_node("cost_agent", cost_node)
    graph.add_node("property_agent", property_node)
    graph.add_node("suitability_agent", suitability_node)
    graph.add_node(
        "decision_explanation_agent",
        decision_explanation_node,
    )

    graph.add_edge(START, "source_planning_agent")
    graph.add_edge("source_planning_agent", "load_properties")
    graph.add_edge("load_properties", "location_agent")
    graph.add_edge("location_agent", "cost_agent")
    graph.add_edge("cost_agent", "property_agent")
    graph.add_edge("property_agent", "suitability_agent")
    graph.add_edge("suitability_agent", "decision_explanation_agent")
    graph.add_edge("decision_explanation_agent", END)
    return graph.compile()


rentwise_graph = build_graph()
