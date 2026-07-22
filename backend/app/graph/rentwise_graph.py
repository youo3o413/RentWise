from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from app.agents.ai_comparison import generate_ai_summary
from app.agents.rule_agents import (
    cost_assessment,
    location_assessment,
    monthly_cost,
    property_assessment,
    suitability_assessment,
)
from app.models.schemas import AgentTrace, Property, UserRequirements
from app.services.property_service import load_properties


class RentWiseState(TypedDict, total=False):
    requirements: UserRequirements
    properties: list[Property]
    location_results: dict[str, Any]
    cost_results: dict[str, Any]
    property_results: dict[str, Any]
    suitability_results: dict[str, Any]
    ranked_results: list[dict[str, Any]]
    summary: str
    mode: str
    trace: list[AgentTrace]


def load_node(state: RentWiseState) -> dict:
    properties = load_properties()
    return {
        "properties": properties,
        "trace": [
            AgentTrace(
                agent="Data Loader",
                status="completed",
                message=f"已載入 {len(properties)} 筆候選房源",
                property_count=len(properties),
            )
        ],
    }


def location_node(state: RentWiseState) -> dict:
    req = state["requirements"]
    results = {p.id: location_assessment(p, req) for p in state["properties"]}
    return {
        "location_results": results,
        "trace": state["trace"] + [
            AgentTrace(
                agent="Location Agent",
                status="completed",
                message="已完成通勤與周邊生活機能分析",
                property_count=len(results),
            )
        ],
    }


def cost_node(state: RentWiseState) -> dict:
    req = state["requirements"]
    results = {p.id: cost_assessment(p, req) for p in state["properties"]}
    return {
        "cost_results": results,
        "trace": state["trace"] + [
            AgentTrace(
                agent="Cost Agent",
                status="completed",
                message="已估算租金、管理費、水電與真實月支出",
                property_count=len(results),
            )
        ],
    }


def property_node(state: RentWiseState) -> dict:
    req = state["requirements"]
    results = {p.id: property_assessment(p, req) for p in state["properties"]}
    return {
        "property_results": results,
        "trace": state["trace"] + [
            AgentTrace(
                agent="Property Agent",
                status="completed",
                message="已檢查窗戶、電梯、樓層、設備與風險",
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


def comparison_node(state: RentWiseState) -> dict:
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
                "estimated_monthly_cost": monthly_cost(p),
                "strengths": list(dict.fromkeys(strengths))[:5],
                "tradeoffs": list(dict.fromkeys(tradeoffs))[:5],
                "assessments": assessments,
            }
        )

    ranked.sort(key=lambda item: item["total_score"], reverse=True)
    for index, item in enumerate(ranked, start=1):
        item["rank"] = index
        if index == 1:
            item["recommendation"] = "最符合目前需求，建議優先安排看房。"
        elif item["total_score"] >= 75:
            item["recommendation"] = "整體條件不錯，可作為備選並比較實際房況。"
        else:
            item["recommendation"] = "存在明顯取捨，除非願意調整需求，否則不優先。"

    summary, mode = generate_ai_summary(state["requirements"], ranked)
    return {
        "ranked_results": ranked,
        "summary": summary,
        "mode": mode,
        "trace": state["trace"] + [
            AgentTrace(
                agent="Comparison Agent",
                status="completed",
                message="已整合所有 Agent 結果並完成最終排名",
                property_count=len(ranked),
            )
        ],
    }


def build_graph():
    graph = StateGraph(RentWiseState)
    graph.add_node("load_properties", load_node)
    graph.add_node("location_agent", location_node)
    graph.add_node("cost_agent", cost_node)
    graph.add_node("property_agent", property_node)
    graph.add_node("suitability_agent", suitability_node)
    graph.add_node("comparison_agent", comparison_node)

    graph.add_edge(START, "load_properties")
    graph.add_edge("load_properties", "location_agent")
    graph.add_edge("location_agent", "cost_agent")
    graph.add_edge("cost_agent", "property_agent")
    graph.add_edge("property_agent", "suitability_agent")
    graph.add_edge("suitability_agent", "comparison_agent")
    graph.add_edge("comparison_agent", END)
    return graph.compile()


rentwise_graph = build_graph()
