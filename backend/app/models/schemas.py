from typing import Literal
from pydantic import BaseModel, Field


NoisePreference = Literal["quiet", "balanced", "no_preference"]


class UserRequirements(BaseModel):
    budget: int = Field(15000, ge=5000, le=100000)
    destination: str = Field("政治大學", min_length=1, max_length=100)
    max_commute_minutes: int = Field(25, ge=1, le=180)
    needs_window: bool = True
    noise_preference: NoisePreference = "quiet"
    needs_elevator: bool = False
    needs_convenience_store: bool = True
    max_floor_without_elevator: int = Field(3, ge=1, le=20)
    preferences: list[str] = Field(default_factory=list)


class Property(BaseModel):
    id: str
    title: str
    address: str
    rent: int
    management_fee: int
    water_fee: int
    electricity_rate: float
    estimated_kwh: int
    commute_minutes: int
    has_window: bool
    window_type: str
    has_elevator: bool
    floor: int
    noise_level: Literal["low", "medium", "high"]
    nearby: list[str]
    features: list[str]
    risks: list[str]
    description: str
    image_url: str


class AgentAssessment(BaseModel):
    agent: str
    property_id: str
    score: float = Field(ge=0, le=100)
    summary: str
    positives: list[str]
    concerns: list[str]
    metrics: dict[str, str | int | float | bool]


class PropertyResult(BaseModel):
    rank: int
    property: Property
    total_score: float
    estimated_monthly_cost: int
    recommendation: str
    strengths: list[str]
    tradeoffs: list[str]
    assessments: dict[str, AgentAssessment]


class AgentTrace(BaseModel):
    agent: str
    status: Literal["completed", "skipped", "failed"]
    message: str
    property_count: int


class RecommendationResponse(BaseModel):
    mode: Literal["ai", "demo"]
    summary: str
    results: list[PropertyResult]
    trace: list[AgentTrace]
