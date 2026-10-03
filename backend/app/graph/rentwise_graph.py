import operator
import sqlite3
from dataclasses import replace
from pathlib import Path
from typing import Annotated, Any, Literal, TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from app.config import use_mock_listings

from app.agents.ai_enrichment import (
    analyze_property_images,
    apply_cost_estimate,
    apply_listing_requirement_analysis,
    apply_property_vision,
    classify_listing_uses,
    estimate_property_costs,
    interpret_listing_requirements,
)
from app.agents.decision_explanation import generate_decision_explanation
from app.agents.rule_agents import (
    cost_assessment,
    location_assessment,
    property_assessment,
    suitability_assessment,
)
from app.models.schemas import (
    AgentAssessment,
    AgentTrace,
    Property,
    SuitabilityWeights,
    UserRequirements,
)
from app.services.commute_service import enrich_commute_data
from app.services.property_service import load_properties_for_requirements
from app.services.rent591_service import Rent591Error
from app.services.source_planning_service import (
    SourceSearchPlan,
    build_source_search_plan,
)


class RentWiseState(TypedDict, total=False):
    requirements: UserRequirements
    source_plan: SourceSearchPlan
    search_attempt: int
    minimum_properties: int
    search_error: str
    original_search_conditions: dict[str, Any]
    current_search_conditions: dict[str, Any]
    relaxed_conditions: list[str]
    properties: list[Property]
    cost_properties: list[Property]
    quality_properties: list[Property]
    location_properties: list[Property]
    location_tool_checked: bool
    location_needs_tool: bool
    location_results: dict[str, AgentAssessment]
    cost_results: dict[str, AgentAssessment]
    property_results: dict[str, AgentAssessment]
    suitability_results: dict[str, AgentAssessment]
    ranked_results: list[dict[str, Any]]
    summary: str
    mode: str
    feedback: dict[str, Any]
    recommendation_accepted: bool
    auto_accept: bool
    trace: Annotated[list[AgentTrace], operator.add]

def source_planning_node(state: RentWiseState) -> dict:
    req = state["requirements"]
    plan = build_source_search_plan(req)
    return {
        "source_plan": plan,
        "search_attempt": 0,
        "original_search_conditions": {
            "destination": req.destination,
            "resolved_address": plan.resolved_address,
            "region_name": plan.region_name,
            "budget": req.budget,
            "max_commute_minutes": req.max_commute_minutes,
        },
        "current_search_conditions": {
            "scope": plan.resolved_address or req.destination,
            "region_name": plan.region_name,
        },
        "relaxed_conditions": [],
        "trace": [
            AgentTrace(
                agent="Source Planning Agent",
                status="completed",
                message=(
                    f"已將「{req.destination}」定位為 {plan.region_name} "
                    f"生活圈，搜尋 {'、'.join(plan.sources)}"
                ),
                property_count=0,
            )
        ],
    }


def search_properties_node(state: RentWiseState) -> dict:
    req = state["requirements"]
    attempt = state.get("search_attempt", 0) + 1
    try:
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
            raise Rent591Error(
                "取得的刊登皆為車位、置物空間或其他非住宅用途。"
            )
        error = ""
    except Rent591Error as exc:
        properties = []
        use_message = str(exc)
        error = str(exc)
    return {
        "properties": properties,
        "search_attempt": attempt,
        "search_error": error,
        "trace": [
            AgentTrace(
                agent="Data Loader",
                status="completed" if properties else "failed",
                message=(
                    (f"已從本機 JSON 載入 {len(properties)} 筆虛構示範房源；"
                     if use_mock_listings(req.property_source)
                     else f"第 {attempt} 次搜尋取得 {len(properties)} 筆可居住房源；")
                    +
                    f"{use_message}"
                ),
                property_count=len(properties),
            )
        ],
    }


def search_route(
    state: RentWiseState,
) -> Literal["adjust_search", "prepare_location_data"]:
    minimum = state.get("minimum_properties", 4)
    count = len(state.get("properties", []))
    if count >= minimum:
        return "prepare_location_data"
    plan = state.get("source_plan")
    district_scope = (
        f"{plan.region_name}{plan.district_name}"
        if plan and plan.district_name
        else ""
    )
    if (
        state.get("search_attempt", 0) < 2
        and district_scope
        and plan
        and plan.resolved_address != district_scope
    ):
        return "adjust_search"
    if count:
        return "prepare_location_data"
    raise Rent591Error(
        state.get("search_error")
        or "調整搜尋範圍後仍找不到可居住房源。"
    )


def adjust_search_node(state: RentWiseState) -> dict:
    plan = state["source_plan"]
    broader_address = f"{plan.region_name}{plan.district_name}"
    adjusted = replace(
        plan,
        resolved_address=broader_address,
        keywords=tuple(
            dict.fromkeys((*plan.keywords, broader_address))
        ),
    )
    return {
        "source_plan": adjusted,
        "current_search_conditions": {
            "scope": broader_address,
            "region_name": plan.region_name,
        },
        "relaxed_conditions": [
            *state.get("relaxed_conditions", []),
            (
                f"搜尋範圍由「{plan.resolved_address or plan.destination}」"
                f"放寬為「{broader_address}」"
            ),
        ],
        "trace": [
            AgentTrace(
                agent="Search Adjustment",
                status="completed",
                message=(
                    f"房源不足，已將搜尋範圍放寬至 {broader_address}，"
                    "不會擴大到整個縣市；"
                    "保留使用者評分條件不變"
                ),
                property_count=len(state.get("properties", [])),
            )
        ],
    }


def prepare_location_data_node(state: RentWiseState) -> dict:
    return {
        "location_tool_checked": False,
        "location_needs_tool": False,
        "trace": [
            AgentTrace(
                agent="Parallel Analysis Dispatcher",
                status="completed",
                message="已將房源送往 Location、Cost、Property 三個既有 Agent",
                property_count=len(state["properties"]),
            )
        ],
    }


def location_node(state: RentWiseState) -> dict:
    req = state["requirements"]
    properties = state.get("location_properties", state["properties"])
    needs_transport = any(
        property_.commute_minutes is None
        or property_.latitude is None
        or property_.longitude is None
        for property_ in properties
    )
    needs_amenities = (
        req.needs_convenience_store
        and any(
            not property_.convenience_store_lookup_completed
            for property_ in properties
        )
    ) or (
        req.needs_parking
        and any(
            not property_.parking_lookup_completed
            for property_ in properties
        )
    )
    needs_tool = (
        not state.get("location_tool_checked", False)
        and (needs_transport or needs_amenities)
    )
    if needs_tool:
        return {
            "location_needs_tool": True,
            "trace": [
                AgentTrace(
                    agent="Location Agent",
                    status="skipped",
                    message="通勤或生活機能資料不足，決定呼叫地圖與交通工具",
                    property_count=len(properties),
                )
            ],
        }
    results = {
        property_.id: location_assessment(property_, req)
        for property_ in properties
    }
    return {
        "location_results": results,
        "location_needs_tool": False,
        "trace": [
            AgentTrace(
                agent="Location Agent",
                status="completed",
                message="已完成通勤、便利商店與停車等原有 Location 分析",
                property_count=len(results),
            )
        ],
    }


def location_route(
    state: RentWiseState,
) -> Literal["location_tool", "location_complete"]:
    return (
        "location_tool"
        if state.get("location_needs_tool", False)
        else "location_complete"
    )


def _location_tool_arguments(
    state: RentWiseState,
) -> tuple[
    UserRequirements,
    SourceSearchPlan | None,
    tuple[float, float] | None,
    str,
]:
    req = state["requirements"]
    plan = state.get("source_plan")
    coordinates = (
        (plan.latitude, plan.longitude)
        if plan and plan.latitude is not None and plan.longitude is not None
        else (
            (req.destination_latitude, req.destination_longitude)
            if req.destination_latitude is not None
            and req.destination_longitude is not None
            else None
        )
    )
    destination = (
        plan.resolved_address
        if plan and plan.resolved_address
        else req.destination_resolved_address or req.destination
    )
    return req, plan, coordinates, destination


def location_tool_node(state: RentWiseState) -> dict:
    req, plan, coordinates, destination = _location_tool_arguments(state)
    properties = state["properties"]
    include_transport = any(
        property_.commute_minutes is None
        or property_.latitude is None
        or property_.longitude is None
        for property_ in properties
    )
    include_amenities = (
        req.needs_convenience_store
        and any(
            not property_.convenience_store_lookup_completed
            for property_ in properties
        )
    ) or (
        req.needs_parking
        and any(
            not property_.parking_lookup_completed
            for property_ in properties
        )
    )
    properties = enrich_commute_data(
        properties,
        destination,
        req.commute_mode,
        req.needs_parking,
        coordinates,
        plan.region_name if plan else "",
        include_transport,
        include_amenities,
    )
    return {
        "location_properties": properties,
        "location_tool_checked": True,
        "location_needs_tool": False,
        "trace": [
            AgentTrace(
                agent="Location Agent Tools",
                status="completed",
                message="已依缺少資料呼叫 TDX、Valhalla、定位或 Overpass 工具",
                property_count=len(properties),
            )
        ],
    }


def location_complete_node(state: RentWiseState) -> dict:
    return {}


def cost_node(state: RentWiseState) -> dict:
    req = state["requirements"]
    estimates, message = estimate_property_costs(req, state["properties"])
    properties = [
        apply_cost_estimate(property_, estimates.get(property_.id))
        for property_ in state["properties"]
    ]
    results = {
        property_.id: cost_assessment(property_, req)
        for property_ in properties
    }
    return {
        "cost_properties": properties,
        "cost_results": results,
        "trace": [
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
    interpreted = [
        apply_listing_requirement_analysis(
            property_,
            requirement_analyses.get(property_.id),
        )
        for property_ in state["properties"]
    ]
    analyses, vision_message = analyze_property_images(interpreted)
    properties = [
        apply_property_vision(property_, analyses.get(property_.id))
        for property_ in interpreted
    ]
    results = {
        property_.id: property_assessment(property_, req)
        for property_ in properties
    }
    return {
        "quality_properties": properties,
        "property_results": results,
        "trace": [
            AgentTrace(
                agent="Property Agent",
                status="completed",
                message=f"{requirement_message}；{vision_message}",
                property_count=len(results),
            )
        ],
    }


COST_FIELDS = (
    "management_fee",
    "water_fee",
    "electricity_rate",
    "estimated_kwh",
    "management_fee_disclosed",
    "water_fee_disclosed",
    "electricity_rate_disclosed",
    "electricity_usage_disclosed",
    "cost_estimated_by_ai",
    "cost_estimate_confidence",
    "cost_estimate_basis",
)
QUALITY_FIELDS = (
    "has_window",
    "window_type",
    "listing_requirements_analyzed_by_ai",
    "listing_requirement_summary",
    "listing_requirement_checks",
    "vision_analyzed_by_ai",
    "vision_window_visible",
    "vision_confidence",
    "vision_summary",
    "space_impression",
    "noise_level",
    "noise_analyzed_by_ai",
    "noise_evidence",
    "noise_confidence",
)
LOCATION_FIELDS = (
    "commute_minutes",
    "distance_reference",
    "commute_method",
    "commute_transfers",
    "route_distance_km",
    "transit_commute_minutes",
    "walking_commute_minutes",
    "walking_distance_km",
    "driving_commute_minutes",
    "driving_distance_km",
    "latitude",
    "longitude",
    "nearby",
    "nearby_convenience_store_count",
    "nearest_convenience_store_meters",
    "nearby_convenience_stores",
    "convenience_store_lookup_completed",
    "nearby_data_source",
    "nearby_parking_count",
    "nearest_parking_meters",
    "nearby_parking_facilities",
    "parking_lookup_completed",
)


def merge_analysis_node(state: RentWiseState) -> dict:
    cost_by_id = {
        property_.id: property_
        for property_ in state.get("cost_properties", [])
    }
    quality_by_id = {
        property_.id: property_
        for property_ in state.get("quality_properties", [])
    }
    location_by_id = {
        property_.id: property_
        for property_ in state.get("location_properties", [])
    }
    merged = []
    for property_ in state["properties"]:
        updates = {}
        cost_property = cost_by_id.get(property_.id)
        quality_property = quality_by_id.get(property_.id)
        location_property = location_by_id.get(property_.id)
        if cost_property:
            updates.update({
                field: getattr(cost_property, field)
                for field in COST_FIELDS
            })
        if quality_property:
            updates.update({
                field: getattr(quality_property, field)
                for field in QUALITY_FIELDS
            })
        if location_property:
            updates.update({
                field: getattr(location_property, field)
                for field in LOCATION_FIELDS
            })
        merged.append(property_.model_copy(update=updates))
    return {
        "properties": merged,
        "trace": [
            AgentTrace(
                agent="Parallel Analysis Join",
                status="completed",
                message="已合併 Location、Cost、Property 三個既有 Agent 結果",
                property_count=len(merged),
            )
        ],
    }


def suitability_node(state: RentWiseState) -> dict:
    req = state["requirements"]
    results = {
        property_.id: suitability_assessment(
            property_,
            req,
            state["location_results"][property_.id],
            state["cost_results"][property_.id],
            state["property_results"][property_.id],
        )
        for property_ in state["properties"]
    }
    return {
        "suitability_results": results,
        "trace": [
            AgentTrace(
                agent="Suitability Agent",
                status="completed",
                message="已依個人偏好完成透明加權與必要條件檢查",
                property_count=len(results),
            )
        ],
    }


def decision_explanation_node(state: RentWiseState) -> dict:
    ranked = []
    for property_ in state["properties"]:
        assessments = {
            "location": state["location_results"][property_.id],
            "cost": state["cost_results"][property_.id],
            "property": state["property_results"][property_.id],
            "suitability": state["suitability_results"][property_.id],
        }
        strengths = []
        tradeoffs = []
        for assessment in assessments.values():
            strengths.extend(assessment.positives)
            tradeoffs.extend(assessment.concerns)
        ranked.append(
            {
                "property": property_,
                "total_score": state["suitability_results"][property_.id].score,
                "estimated_monthly_cost": state["cost_results"][
                    property_.id
                ].metrics["estimated_monthly_cost"],
                "strengths": list(dict.fromkeys(strengths))[:5],
                "tradeoffs": list(dict.fromkeys(tradeoffs))[:5],
                "assessments": assessments,
            }
        )
    ranked.sort(
        key=lambda item: (
            {
                "qualified": 2,
                "needs_verification": 1,
            }.get(
                item["assessments"]["suitability"].metrics.get(
                    "qualification_status",
                    "qualified",
                ),
                0,
            ),
            item["total_score"],
            item["assessments"]["property"].metrics.get(
                "data_completeness", 0
            ),
        ),
        reverse=True,
    )
    for index, item in enumerate(ranked, start=1):
        item["rank"] = index
        suitability = item["assessments"]["suitability"]
        qualification_status = suitability.metrics.get(
            "qualification_status",
            "qualified",
        )
        if qualification_status == "needs_verification":
            issues = list(
                filter(
                    None,
                    (
                        suitability.metrics.get("disqualifying_conflicts", ""),
                        suitability.metrics.get("pending_conditions", ""),
                    ),
                )
            )
            item["recommendation"] = (
                f"仍有條件需要確認（{'、'.join(issues) or '必要條件'}），"
                "目前列為待確認候選。"
            )
        elif index == 1:
            item["recommendation"] = "最符合目前需求，建議優先安排看房。"
        elif item["total_score"] >= 75:
            item["recommendation"] = "整體條件不錯，可作為備選並實地比較。"
        else:
            item["recommendation"] = "存在明顯取捨，建議先調整條件再決定。"
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
        "trace": [
            AgentTrace(
                agent="Decision Explanation Agent",
                status="completed",
                message=(
                    "已依確定性評分完成排序，再由 OpenAI 產生決策說明"
                    if mode == "ai"
                    else "已依透明公式完成排序與規則式決策說明"
                ),
                property_count=len(ranked),
            )
        ],
    }


def recommendation_feedback_node(state: RentWiseState) -> dict:
    if state.get("auto_accept", False):
        return {"recommendation_accepted": True}
    answer = interrupt(
        {
            "kind": "recommendation_feedback",
            "prompt": "這份推薦是否符合你的偏好？",
            "current_weights": state["requirements"].weights.model_dump(),
            "top_result": (
                state["ranked_results"][0]["property"].title
                if state.get("ranked_results")
                else ""
            ),
        }
    )
    feedback = answer if isinstance(answer, dict) else {"accepted": bool(answer)}
    return {
        "feedback": feedback,
        "recommendation_accepted": bool(feedback.get("accepted", False)),
    }


def feedback_route(
    state: RentWiseState,
) -> Literal["update_preferences", "__end__"]:
    return (
        END
        if state.get("recommendation_accepted", False)
        else "update_preferences"
    )


def update_preferences_node(state: RentWiseState) -> dict:
    req = state["requirements"]
    feedback = state.get("feedback", {})
    weights_payload = feedback.get("weights")
    if weights_payload:
        weights = SuitabilityWeights.model_validate(weights_payload)
        req = req.model_copy(update={"weights": weights})
        message = "已依使用者調整的權重更新 State"
    else:
        message = "未收到新權重，保留目前偏好重新檢查"
    return {
        "requirements": req,
        "recommendation_accepted": False,
        "trace": [
            AgentTrace(
                agent="Human Feedback",
                status="completed",
                message=message,
                property_count=len(state.get("properties", [])),
            )
        ],
    }


def build_graph():
    graph = StateGraph(RentWiseState)
    graph.add_node("source_planning_agent", source_planning_node)
    graph.add_node("load_properties", search_properties_node)
    graph.add_node("adjust_search", adjust_search_node)
    graph.add_node("prepare_location_data", prepare_location_data_node)
    graph.add_node("location_agent", location_node)
    graph.add_node("location_tool", location_tool_node)
    graph.add_node("location_complete", location_complete_node)
    graph.add_node("cost_agent", cost_node)
    graph.add_node("property_agent", property_node)
    graph.add_node("merge_parallel_analysis", merge_analysis_node)
    graph.add_node("suitability_agent", suitability_node)
    graph.add_node(
        "decision_explanation_agent",
        decision_explanation_node,
    )
    graph.add_node("recommendation_feedback", recommendation_feedback_node)
    graph.add_node("update_preferences", update_preferences_node)

    graph.add_edge(START, "source_planning_agent")
    graph.add_edge("source_planning_agent", "load_properties")
    graph.add_conditional_edges("load_properties", search_route)
    graph.add_edge("adjust_search", "load_properties")
    graph.add_edge("prepare_location_data", "location_agent")
    graph.add_edge("prepare_location_data", "cost_agent")
    graph.add_edge("prepare_location_data", "property_agent")
    graph.add_conditional_edges("location_agent", location_route)
    graph.add_edge("location_tool", "location_agent")
    graph.add_edge(
        [
            "location_complete",
            "cost_agent",
            "property_agent",
        ],
        "merge_parallel_analysis",
    )
    graph.add_edge("merge_parallel_analysis", "suitability_agent")
    graph.add_edge(
        "suitability_agent",
        "decision_explanation_agent",
    )
    graph.add_edge(
        "decision_explanation_agent",
        "recommendation_feedback",
    )
    graph.add_conditional_edges("recommendation_feedback", feedback_route)
    graph.add_edge("update_preferences", "suitability_agent")
    checkpoint_path = (
        Path(__file__).resolve().parents[2]
        / "rentwise_checkpoints.sqlite3"
    )
    checkpoint_connection = sqlite3.connect(
        checkpoint_path,
        check_same_thread=False,
    )
    return graph.compile(
        checkpointer=SqliteSaver(checkpoint_connection)
    )


rentwise_graph = build_graph()
