from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.graph.rentwise_graph import rentwise_graph
from app.models.schemas import (
    Property,
    PropertyResult,
    RecommendationResponse,
    UserRequirements,
)
from app.services.property_service import load_properties

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


@app.post("/api/recommend", response_model=RecommendationResponse)
def recommend(requirements: UserRequirements) -> RecommendationResponse:
    final_state = rentwise_graph.invoke({"requirements": requirements})
    results = [
        PropertyResult.model_validate(item)
        for item in final_state["ranked_results"]
    ]
    return RecommendationResponse(
        mode=final_state["mode"],
        summary=final_state["summary"],
        results=results,
        trace=final_state["trace"],
    )
