from app.models.schemas import AgentAssessment, Property, UserRequirements


def _clamp(value: float) -> float:
    return round(max(0, min(100, value)), 1)


def monthly_cost(property_: Property) -> int:
    electricity = round(property_.electricity_rate * property_.estimated_kwh)
    return property_.rent + property_.management_fee + property_.water_fee + electricity


def location_assessment(property_: Property, req: UserRequirements) -> AgentAssessment:
    score = 100.0
    positives, concerns = [], []

    if property_.commute_minutes <= req.max_commute_minutes:
        margin = req.max_commute_minutes - property_.commute_minutes
        score += min(5, margin * 0.3)
        positives.append(f"通勤約 {property_.commute_minutes} 分鐘，符合上限")
    else:
        over = property_.commute_minutes - req.max_commute_minutes
        score -= 35 + over * 1.5
        concerns.append(f"通勤超出上限 {over} 分鐘")

    has_store = "便利商店" in property_.nearby
    if req.needs_convenience_store and has_store:
        positives.append("步行生活圈包含便利商店")
    elif req.needs_convenience_store:
        score -= 18
        concerns.append("房源資料未顯示附近有便利商店")

    if len(property_.nearby) >= 4:
        score += 4
        positives.append("周邊生活機能完整")

    return AgentAssessment(
        agent="Location Agent",
        property_id=property_.id,
        score=_clamp(score),
        summary=f"分析通勤與 {len(property_.nearby)} 項周邊機能。",
        positives=positives,
        concerns=concerns,
        metrics={
            "commute_minutes": property_.commute_minutes,
            "commute_limit": req.max_commute_minutes,
            "has_convenience_store": has_store,
            "nearby_count": len(property_.nearby),
        },
    )


def cost_assessment(property_: Property, req: UserRequirements) -> AgentAssessment:
    cost = monthly_cost(property_)
    gap = req.budget - cost
    positives, concerns = [], []

    if gap >= 0:
        score = 82 + min(18, gap / max(req.budget, 1) * 90)
        positives.append(f"預估月支出低於預算 {gap:,} 元")
    else:
        over_ratio = abs(gap) / req.budget
        score = 75 - over_ratio * 160
        concerns.append(f"預估月支出超出預算 {abs(gap):,} 元")

    if property_.electricity_rate > 6:
        score -= 8
        concerns.append(f"每度電 {property_.electricity_rate:g} 元偏高")
    else:
        positives.append(f"每度電 {property_.electricity_rate:g} 元")

    return AgentAssessment(
        agent="Cost Agent",
        property_id=property_.id,
        score=_clamp(score),
        summary=f"租金加固定費用與預估電費後，每月約 {cost:,} 元。",
        positives=positives,
        concerns=concerns,
        metrics={
            "rent": property_.rent,
            "management_fee": property_.management_fee,
            "estimated_monthly_cost": cost,
            "budget_gap": gap,
        },
    )


def property_assessment(property_: Property, req: UserRequirements) -> AgentAssessment:
    score = 88.0
    positives, concerns = [], []

    if property_.has_window:
        positives.append(f"具備{property_.window_type}")
        score += 6
    elif req.needs_window:
        score -= 48
        concerns.append("缺少真正對外窗，與必要條件衝突")

    if property_.has_elevator:
        positives.append("有電梯")
        score += 4
    elif property_.floor > req.max_floor_without_elevator:
        penalty = 8 + (property_.floor - req.max_floor_without_elevator) * 5
        score -= penalty
        concerns.append(f"{property_.floor} 樓無電梯，超過可接受樓層")

    if req.needs_elevator and not property_.has_elevator:
        score -= 32
        concerns.append("使用者要求電梯，但房源無電梯")

    positives.extend(property_.features[:2])
    concerns.extend(property_.risks[:2])

    return AgentAssessment(
        agent="Property Agent",
        property_id=property_.id,
        score=_clamp(score),
        summary="檢查窗戶、電梯、樓層、設備與房源風險。",
        positives=list(dict.fromkeys(positives)),
        concerns=list(dict.fromkeys(concerns)),
        metrics={
            "has_window": property_.has_window,
            "window_type": property_.window_type,
            "has_elevator": property_.has_elevator,
            "floor": property_.floor,
        },
    )


def suitability_assessment(
    property_: Property,
    req: UserRequirements,
    location: AgentAssessment,
    cost: AgentAssessment,
    property_result: AgentAssessment,
) -> AgentAssessment:
    weighted = location.score * 0.30 + cost.score * 0.30 + property_result.score * 0.25
    positives, concerns = [], []

    noise_score = 80.0
    if req.noise_preference == "quiet":
        if property_.noise_level == "low":
            noise_score = 100
            positives.append("安靜程度符合偏好")
        elif property_.noise_level == "medium":
            noise_score = 65
            concerns.append("環境可能偶爾有噪音")
        else:
            noise_score = 25
            concerns.append("環境較吵，與安靜偏好衝突")
    elif req.noise_preference == "balanced":
        noise_score = {"low": 95, "medium": 85, "high": 55}[property_.noise_level]

    feature_matches = [
        preference for preference in req.preferences
        if any(preference in feature or feature in preference for feature in property_.features)
    ]
    if feature_matches:
        positives.append("符合偏好：" + "、".join(feature_matches))
        weighted += min(5, len(feature_matches) * 2.5)

    total = weighted + noise_score * 0.15

    hard_conflicts = []
    if req.needs_window and not property_.has_window:
        hard_conflicts.append("對外窗")
    if req.needs_elevator and not property_.has_elevator:
        hard_conflicts.append("電梯")
    if hard_conflicts:
        total -= 12 * len(hard_conflicts)
        concerns.append("必要條件衝突：" + "、".join(hard_conflicts))

    return AgentAssessment(
        agent="Suitability Agent",
        property_id=property_.id,
        score=_clamp(total),
        summary="將地點、成本、房況與個人生活偏好加權整合。",
        positives=positives,
        concerns=concerns,
        metrics={
            "location_weight": 0.30,
            "cost_weight": 0.30,
            "property_weight": 0.25,
            "noise_weight": 0.15,
            "noise_level": property_.noise_level,
        },
    )
