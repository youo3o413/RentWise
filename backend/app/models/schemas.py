from typing import Literal
from pydantic import BaseModel, Field, model_validator


NoisePreference = Literal["quiet", "balanced", "no_preference"]
CommuteMode = Literal["transit_walk", "drive"]


class SuitabilityWeights(BaseModel):
    location: int = Field(30, ge=0, le=100)
    cost: int = Field(30, ge=0, le=100)
    property: int = Field(25, ge=0, le=100)
    noise: int = Field(15, ge=0, le=100)

    @model_validator(mode="after")
    def require_positive_total(self):
        if self.location + self.cost + self.property + self.noise <= 0:
            raise ValueError("至少需要設定一項適配權重")
        return self


class UserRequirements(BaseModel):
    budget: int = Field(15000, ge=5000, le=100000)
    destination: str = Field("政治大學", min_length=1, max_length=100)
    destination_resolved_address: str = Field("", max_length=500)
    destination_latitude: float | None = None
    destination_longitude: float | None = None
    max_commute_minutes: int = Field(25, ge=1, le=180)
    needs_window: bool = True
    noise_preference: NoisePreference = "quiet"
    needs_elevator: bool = False
    needs_convenience_store: bool = True
    max_floor_without_elevator: int = Field(3, ge=1, le=20)
    preferences: list[str] = Field(default_factory=list)
    property_source: Literal["multi", "591", "demo"] = "multi"
    weights: SuitabilityWeights = Field(default_factory=SuitabilityWeights)
    commute_mode: CommuteMode = "transit_walk"
    needs_parking: bool = False
    needs_rental_subsidy: bool = False
    use_community_evidence: bool = False


class RequirementParseRequest(BaseModel):
    text: str = Field(min_length=3, max_length=1000)
    current: UserRequirements = Field(default_factory=UserRequirements)


class RequirementParseResponse(BaseModel):
    requirements: UserRequirements
    interpretation: str
    assumptions: list[str] = Field(default_factory=list)
    updated_fields: list[str] = Field(default_factory=list)
    mode: Literal["ai"]


class DestinationResolveRequest(BaseModel):
    query: str = Field(min_length=1, max_length=100)


class DestinationResolveResponse(BaseModel):
    query: str
    resolved_label: str
    resolved_address: str
    region_name: str
    district_name: str = ""
    latitude: float | None = None
    longitude: float | None = None
    source: Literal["openstreetmap", "administrative_rules"]
    confidence: Literal["medium", "high"]


class PropertySourceLink(BaseModel):
    name: str
    url: str


class Property(BaseModel):
    id: str
    title: str
    address: str
    rent: int
    management_fee: int
    water_fee: int
    electricity_rate: float
    estimated_kwh: int
    management_fee_disclosed: bool = True
    water_fee_disclosed: bool = True
    electricity_rate_disclosed: bool = True
    electricity_usage_disclosed: bool = True
    cost_estimated_by_ai: bool = False
    cost_estimate_confidence: Literal["low", "medium", "high"] | None = None
    cost_estimate_basis: list[str] = Field(default_factory=list)
    commute_minutes: int | None
    distance_reference: str = ""
    commute_method: str = ""
    commute_transfers: int | None = None
    route_distance_km: float | None = None
    transit_commute_minutes: int | None = None
    walking_commute_minutes: int | None = None
    walking_distance_km: float | None = None
    driving_commute_minutes: int | None = None
    driving_distance_km: float | None = None
    latitude: float | None = None
    longitude: float | None = None
    has_window: bool | None
    window_type: str
    has_elevator: bool | None
    floor: int | None
    noise_level: Literal["low", "medium", "high"] | None
    nearby: list[str]
    nearby_convenience_store_count: int | None = None
    nearest_convenience_store_meters: int | None = None
    nearby_data_source: str = ""
    nearby_parking_count: int | None = None
    nearest_parking_meters: int | None = None
    rental_subsidy_eligible: bool | None = None
    vision_analyzed_by_ai: bool = False
    vision_window_visible: bool = False
    vision_confidence: Literal["low", "medium", "high"] | None = None
    vision_summary: str = ""
    space_impression: Literal["spacious", "adequate", "compact", "unknown"] = "unknown"
    listing_area_ping: float | None = None
    features: list[str]
    risks: list[str]
    description: str
    image_url: str
    source_name: str = "Demo"
    source_url: str = ""
    source_links: list[PropertySourceLink] = Field(default_factory=list)
    data_notes: list[str] = Field(default_factory=list)


class ConditionCheck(BaseModel):
    label: str
    status: Literal["met", "unmet", "unknown", "not_required"]
    evidence: str


class AgentAssessment(BaseModel):
    agent: str
    property_id: str
    score: float = Field(ge=0, le=100)
    summary: str
    positives: list[str]
    concerns: list[str]
    metrics: dict[str, str | int | float | bool]
    checks: list[ConditionCheck] = Field(default_factory=list)


class EvidenceSource(BaseModel):
    title: str
    url: str


class CommunityFinding(BaseModel):
    topic: str
    sentiment: Literal["positive", "mixed", "negative", "no_evidence"]
    scope: Literal["exact_property", "same_building", "nearby_area", "general_area"]
    summary: str


class CommunityEvidence(BaseModel):
    status: Literal["found", "not_found", "unavailable"]
    summary: str
    confidence: Literal["low", "medium"]
    searched_preferences: list[str]
    findings: list[CommunityFinding] = Field(default_factory=list)
    sources: list[EvidenceSource] = Field(default_factory=list)
    disclaimer: str = (
        "公開社群意見僅供參考，不能代替房東或租約確認。"
    )


class PropertyResult(BaseModel):
    rank: int
    property: Property
    total_score: float
    estimated_monthly_cost: int
    recommendation: str
    strengths: list[str]
    tradeoffs: list[str]
    assessments: dict[str, AgentAssessment]
    community_evidence: CommunityEvidence | None = None


class AgentTrace(BaseModel):
    agent: str
    status: Literal["completed", "skipped", "failed"]
    message: str
    property_count: int


class RecommendationResponse(BaseModel):
    mode: Literal["ai", "demo"]
    property_source: Literal["multi", "591", "demo"]
    summary: str
    results: list[PropertyResult]
    trace: list[AgentTrace]


class MapPropertyInput(BaseModel):
    id: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=200)
    address: str = Field(min_length=1, max_length=300)
    score: float = Field(ge=0, le=100)
    source_url: str = Field("", max_length=500)
    latitude: float | None = None
    longitude: float | None = None


class MapContextRequest(BaseModel):
    destination: str = Field(min_length=1, max_length=100)
    destination_address: str = Field("", max_length=500)
    destination_latitude: float | None = None
    destination_longitude: float | None = None
    properties: list[MapPropertyInput] = Field(min_length=1, max_length=6)


class MapPoint(BaseModel):
    id: str
    title: str
    address: str
    latitude: float
    longitude: float
    kind: Literal["destination", "property", "store", "parking"]
    score: float | None = None
    source_url: str = ""
    is_approximate: bool = False


class MapContextResponse(BaseModel):
    destination: MapPoint | None
    properties: list[MapPoint]
    convenience_stores: list[MapPoint]
    parking_facilities: list[MapPoint] = Field(default_factory=list)
    warnings: list[str]
