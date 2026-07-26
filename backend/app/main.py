from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

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
    Property,
    PropertyResult,
    MapContextRequest,
    MapContextResponse,
    DestinationResolveRequest,
    DestinationResolveResponse,
    RecommendationResponse,
    RequirementParseRequest,
    RequirementParseResponse,
    UserRequirements,
)
from app.services.property_service import load_properties
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


@app.get("/api/properties", response_model=list[Property])
def properties() -> list[Property]:
    return load_properties()


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
def recommend(requirements: UserRequirements) -> RecommendationResponse:
    try:
        final_state = rentwise_graph.invoke({"requirements": requirements})
    except Rent591Error as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    results = [
        PropertyResult.model_validate(item)
        for item in final_state["ranked_results"]
    ]
    return RecommendationResponse(
        mode=final_state["mode"],
        property_source=requirements.property_source,
        summary=final_state["summary"],
        results=results,
        trace=final_state["trace"],
    )
