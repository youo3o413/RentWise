from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from langgraph.types import Command

from app.config import get_settings
from app.graph.rentwise_graph import rentwise_graph
from app.agents.requirement_agent import (
    RequirementAgentAuthenticationError,
    RequirementAgentError,
    RequirementAgentQuotaError,
    RequirementAgentUnavailable,
    parse_natural_language_requirements,
)
from app.models.schemas import (
    AgentTrace,
    PropertyResult,
    MapContextRequest,
    MapContextResponse,
    DestinationResolveRequest,
    DestinationResolveResponse,
    RecommendationResponse,
    RecommendationRequest,
    RecommendationFeedbackRequest,
    RequirementParseRequest,
    RequirementParseResponse,
    UserRequirements,
)
from app.services.rent591_service import Rent591Error
from app.services.map_service import build_map_context
from app.services.destination_service import resolve_destination

settings = get_settings()

app = FastAPI(
    title="RentWise API",
    description="LangGraph Multi-Agent 智慧租屋決策平台",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin, "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root() -> dict[str, str]:
    return {"message": "RentWise API is running", "docs": "/docs"}


@app.get("/api/health")
def health() -> dict[str, str | bool]:
    return {
        "status": "ok",
        "openai_enabled": bool(settings.openai_api_key),
        "model": settings.openai_model,
    }


@app.post(
    "/api/parse-requirements",
    response_model=RequirementParseResponse,
)
def parse_requirements(
    request: RequirementParseRequest,
) -> RequirementParseResponse:
    try:
        return parse_natural_language_requirements(
            request.text,
            request.current,
        )
    except RequirementAgentUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except RequirementAgentQuotaError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except RequirementAgentAuthenticationError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except RequirementAgentError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/map-context", response_model=MapContextResponse)
def map_context(request: MapContextRequest) -> MapContextResponse:
    return build_map_context(request)


@app.post(
    "/api/resolve-destination",
    response_model=DestinationResolveResponse,
)
def resolve_destination_endpoint(
    request: DestinationResolveRequest,
) -> DestinationResolveResponse:
    try:
        return resolve_destination(request.query)
    except Rent591Error as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/recommend", response_model=RecommendationResponse)
def recommend(request: RecommendationRequest) -> RecommendationResponse:
    requirements = UserRequirements.model_validate(
        request.model_dump(
            exclude={"requirement_text", "requirements_parsed"}
        )
    )
    try:
        requirement_message = "已接收使用者確認的結構化表單需求"
        if request.requirement_text.strip():
            if request.requirements_parsed:
                requirement_message = "已沿用 Requirement Agent 事前解析結果"
            else:
                parsed = parse_natural_language_requirements(
                    request.requirement_text,
                    requirements,
                )
                requirements = parsed.requirements
                requirement_message = (
                    f"已在 LangGraph 前完成需求解析：{parsed.interpretation}"
                )
        requirement_trace = AgentTrace(
            agent="Requirement Agent",
            status="completed",
            message=requirement_message,
            property_count=0,
        )
        thread_id = str(uuid4())
        config = {"configurable": {"thread_id": thread_id}}
        final_state = rentwise_graph.invoke(
            {
                "requirements": requirements,
                "minimum_properties": 4,
                "auto_accept": False,
                "trace": [requirement_trace],
            },
            config=config,
        )
    except RequirementAgentUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except RequirementAgentQuotaError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except RequirementAgentAuthenticationError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except RequirementAgentError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Rent591Error as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return _recommendation_response(final_state, thread_id)


def _recommendation_response(
    state: dict,
    thread_id: str,
) -> RecommendationResponse:
    interrupts = state.get("__interrupt__") or ()
    results = [
        PropertyResult.model_validate(item)
        for item in state["ranked_results"]
    ]
    requirements = state["requirements"]
    return RecommendationResponse(
        mode=state["mode"],
        property_source=requirements.property_source,
        summary=state["summary"],
        results=results,
        trace=state["trace"],
        thread_id=thread_id,
        awaiting_feedback=bool(interrupts),
        workflow_status=(
            "awaiting_feedback" if interrupts else "completed"
        ),
        current_weights=requirements.weights,
    )


@app.get(
    "/api/recommend/{thread_id}",
    response_model=RecommendationResponse,
)
def get_recommendation_state(thread_id: str) -> RecommendationResponse:
    config = {"configurable": {"thread_id": thread_id}}
    snapshot = rentwise_graph.get_state(config)
    if not snapshot.values:
        raise HTTPException(status_code=404, detail="找不到已保存的推薦流程。")
    state = dict(snapshot.values)
    if snapshot.interrupts:
        state["__interrupt__"] = snapshot.interrupts
    return _recommendation_response(state, thread_id)


@app.post(
    "/api/recommend/{thread_id}/feedback",
    response_model=RecommendationResponse,
)
def recommendation_feedback(
    thread_id: str,
    request: RecommendationFeedbackRequest,
) -> RecommendationResponse:
    config = {"configurable": {"thread_id": thread_id}}
    snapshot = rentwise_graph.get_state(config)
    if not snapshot.values:
        raise HTTPException(status_code=404, detail="找不到這次推薦流程，請重新分析。")
    try:
        state = rentwise_graph.invoke(
            Command(
                resume={
                    "accepted": request.accepted,
                    "weights": (
                        request.weights.model_dump()
                        if request.weights is not None
                        else None
                    ),
                }
            ),
            config=config,
        )
    except Rent591Error as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return _recommendation_response(state, thread_id)
