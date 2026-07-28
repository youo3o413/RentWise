from app.models.schemas import (
    AgentAssessment,
    ConditionCheck,
    Property,
    UserRequirements,
)


def _clamp(value: float) -> float:
    return round(max(0, min(100, value)), 1)


def monthly_cost(property_: Property) -> int:
    electricity = round(property_.electricity_rate * property_.estimated_kwh)
    return property_.rent + property_.management_fee + property_.water_fee + electricity


def _commute_ratio_score(ratio: float) -> float:
    if ratio <= 0.6:
        return 100
    if ratio <= 1:
        return 100 - (ratio - 0.6) / 0.4 * 30
    if ratio <= 1.5:
        return 70 - (ratio - 1) / 0.5 * 50
    if ratio <= 2:
        return 20 - (ratio - 1.5) / 0.5 * 20
    return 0


def _budget_ratio_score(ratio: float) -> float:
    if ratio <= 0.7:
        return 100
    if ratio <= 1:
        return 100 - (ratio - 0.7) / 0.3 * 30
    if ratio <= 1.2:
        return 70 - (ratio - 1) / 0.2 * 70
    return 0


def _distance_score(distance: int | None) -> float | None:
    if distance is None:
        return None
    if distance <= 100:
        return 100
    if distance <= 250:
        return 100 - (distance - 100) / 150 * 15
    if distance <= 500:
        return 85 - (distance - 250) / 250 * 15
    return 0


def location_assessment(property_: Property, req: UserRequirements) -> AgentAssessment:
    positives, concerns = [], []
    commute_available = property_.commute_minutes is not None
    commute_ratio = (
        property_.commute_minutes / req.max_commute_minutes
        if commute_available
        else None
    )
    commute_score = (
        _commute_ratio_score(commute_ratio)
        if commute_ratio is not None
        else None
    )
    if not commute_available:
        concerns.append("房源地址無法定位，通勤時間仍需確認")
    elif commute_ratio <= 1:
        positives.append(f"通勤約 {property_.commute_minutes} 分鐘，符合上限")
    else:
        concerns.append(
            f"通勤超出上限 {property_.commute_minutes - req.max_commute_minutes} 分鐘"
        )

    has_store = (
        "便利商店" in property_.nearby
        or (
            property_.nearby_convenience_store_count is not None
            and property_.nearby_convenience_store_count > 0
        )
    )
    store_available = (
        "便利商店" in property_.nearby
        or property_.nearby_convenience_store_count is not None
    )
    store_score = _distance_score(property_.nearest_convenience_store_meters)
    if store_score is None and has_store:
        store_score = 75
    elif store_score is None and store_available:
        store_score = 0
    if req.needs_convenience_store and has_store:
        if property_.nearest_convenience_store_meters is not None:
            positives.append(
                "OpenStreetMap 顯示最近便利商店約 "
                f"{property_.nearest_convenience_store_meters} 公尺"
            )
        else:
            positives.append("步行生活圈包含便利商店")
    elif req.needs_convenience_store and store_available:
        concerns.append("OpenStreetMap 在 500 公尺內未找到便利商店")
    elif req.needs_convenience_store:
        concerns.append("附近便利商店資料待確認，不納入分數")

    parking_available = property_.nearby_parking_count is not None
    parking_score = _distance_score(property_.nearest_parking_meters)
    if (
        parking_score is None
        and property_.nearby_parking_count is not None
        and property_.nearby_parking_count > 0
    ):
        parking_score = 75
    elif parking_score is None and parking_available:
        parking_score = 0
    if req.needs_parking:
        if (
            property_.nearby_parking_count is not None
            and property_.nearby_parking_count > 0
        ):
            positives.append(
                f"500 公尺內有 {property_.nearby_parking_count} 處停車設施"
            )
        elif property_.nearby_parking_count == 0:
            concerns.append("OpenStreetMap 未找到 500 公尺內停車場")
        else:
            concerns.append("附近停車資訊待確認，不納入分數")

    active_components = ["commute"]
    if req.needs_convenience_store and store_available:
        active_components.append("store")
    if req.needs_parking and parking_available:
        active_components.append("parking")
    component_weight = 1 / len(active_components)
    component_weights = {
        name: component_weight
        for name in active_components
    }
    component_scores = {
        "commute": commute_score,
        "store": store_score,
        "parking": parking_score,
    }
    score = sum(
        (component_scores[name] or 0) * weight
        for name, weight in component_weights.items()
    )

    return AgentAssessment(
        agent="Location Agent",
        property_id=property_.id,
        score=_clamp(score),
        summary=(
            (
                f"依{property_.commute_method or '所在地'}計算通勤，"
                f"並分析 {len(property_.nearby)} 項周邊機能。"
            )
            if property_.commute_minutes is not None
            else f"分析 {len(property_.nearby)} 項周邊機能；通勤時間待確認。"
        ),
        positives=positives,
        concerns=concerns,
        metrics={
            "commute_minutes": (
                property_.commute_minutes
                if property_.commute_minutes is not None
                else "unknown"
            ),
            "commute_limit": req.max_commute_minutes,
            "commute_ratio": (
                round(commute_ratio, 3) if commute_ratio is not None else "unknown"
            ),
            "commute_score": (
                round(commute_score, 1) if commute_score is not None else "unknown"
            ),
            "score_available": commute_available,
            "commute_component_weight": round(component_weights["commute"], 2),
            "store_component_weight": round(component_weights.get("store", 0), 2),
            "parking_component_weight": round(
                component_weights.get("parking", 0), 2
            ),
            "store_score": (
                round(store_score, 1) if store_score is not None else "unknown"
            ),
            "parking_score": (
                round(parking_score, 1)
                if parking_score is not None
                else "unknown"
            ),
            "formula_version": "RentWise Scoring v1.3",
            "commute_method": property_.commute_method or "unknown",
            "commute_transfers": (
                property_.commute_transfers
                if property_.commute_transfers is not None
                else "not_applicable"
            ),
            "has_convenience_store": has_store,
            "convenience_store_count_500m": (
                property_.nearby_convenience_store_count
                if property_.nearby_convenience_store_count is not None
                else "unknown"
            ),
            "nearest_convenience_store_meters": (
                property_.nearest_convenience_store_meters
                if property_.nearest_convenience_store_meters is not None
                else "unknown"
            ),
            "nearby_data_source": property_.nearby_data_source or "listing",
            "commute_mode": req.commute_mode,
            "parking_count_500m": (
                property_.nearby_parking_count
                if property_.nearby_parking_count is not None
                else "unknown"
            ),
            "nearest_parking_meters": (
                property_.nearest_parking_meters
                if property_.nearest_parking_meters is not None
                else "unknown"
            ),
            "nearby_count": len(property_.nearby),
        },
    )


def cost_assessment(property_: Property, req: UserRequirements) -> AgentAssessment:
    cost = monthly_cost(property_)
    gap = req.budget - cost
    cost_ratio = cost / req.budget
    positives, concerns = [], []
    score = _budget_ratio_score(cost_ratio)
    if cost_ratio <= 1:
        positives.append(f"預估月支出低於預算 {gap:,} 元")
    else:
        concerns.append(f"預估月支出超出預算 {abs(gap):,} 元")

    if property_.electricity_rate > 6:
        concerns.append(f"每度電 {property_.electricity_rate:g} 元偏高")
    else:
        positives.append(f"每度電 {property_.electricity_rate:g} 元")
    if property_.cost_estimated_by_ai:
        positives.append(
            "AI 已依所在地、坪數與房型補估刊登未揭露費用"
        )
        concerns.extend(
            f"AI 估算依據：{basis}"
            for basis in property_.cost_estimate_basis[:2]
        )

    return AgentAssessment(
        agent="Cost Agent",
        property_id=property_.id,
        score=_clamp(score),
        summary=(
            f"租金加固定費用與預估電費後，每月約 {cost:,} 元。"
            + (
                f" 未揭露費用由 AI 補估（可信度"
                f"{property_.cost_estimate_confidence}）。"
                if property_.cost_estimated_by_ai
                else ""
            )
        ),
        positives=positives,
        concerns=concerns,
        metrics={
            "rent": property_.rent,
            "management_fee": property_.management_fee,
            "estimated_monthly_cost": cost,
            "budget_gap": gap,
            "budget": req.budget,
            "cost_ratio": round(cost_ratio, 3),
            "score_available": True,
            "formula_version": "RentWise Scoring v1.3",
            "estimate_source": (
                "openai"
                if property_.cost_estimated_by_ai
                else "listing"
                if (
                    property_.management_fee_disclosed
                    and property_.water_fee_disclosed
                    and property_.electricity_rate_disclosed
                )
                else "fallback_estimate"
            ),
            "ai_used": property_.cost_estimated_by_ai,
            "ai_confidence": property_.cost_estimate_confidence or "not_used",
        },
    )


def property_assessment(property_: Property, req: UserRequirements) -> AgentAssessment:
    checks = []
    positives, concerns = [], []
    source_label = property_.source_name or "租屋平台"

    if req.needs_window:
        if property_.has_window is True:
            checks.append(
                ConditionCheck(
                    label="對外窗",
                    status="met",
                    evidence=(
                        f"AI 圖片判讀看到：{property_.window_type}"
                        f"（可信度 {property_.vision_confidence}）"
                        if property_.vision_window_visible
                        else f"{source_label}刊登顯示：{property_.window_type}"
                    ),
                )
            )
        elif property_.has_window is False:
            checks.append(
                ConditionCheck(
                    label="對外窗",
                    status="unmet",
                    evidence="刊登資訊明確顯示沒有對外窗",
                )
            )
        else:
            checks.append(
                ConditionCheck(
                    label="對外窗",
                    status="unknown",
                    evidence=f"{source_label}刊登未揭露，需向出租方確認",
                )
            )

    if req.needs_elevator:
        elevator_status = (
            "met"
            if property_.has_elevator is True
            else "unmet"
            if property_.has_elevator is False
            else "unknown"
        )
        elevator_evidence = (
            f"{source_label}刊登標示有電梯"
            if property_.has_elevator is True
            else f"{source_label}刊登標示無電梯"
            if property_.has_elevator is False
            else f"{source_label}刊登未揭露，需向出租方確認"
        )
        checks.append(
            ConditionCheck(
                label="電梯",
                status=elevator_status,
                evidence=elevator_evidence,
            )
        )

    if req.needs_rental_subsidy:
        subsidy_status = (
            "met"
            if property_.rental_subsidy_eligible is True
            else "unmet"
            if property_.rental_subsidy_eligible is False
            else "unknown"
        )
        checks.append(
            ConditionCheck(
                label="租金補貼",
                status=subsidy_status,
                evidence=(
                    f"{source_label}刊登明確標示可申請或配合租補"
                    if property_.rental_subsidy_eligible is True
                    else f"{source_label}刊登明確標示不配合租補"
                    if property_.rental_subsidy_eligible is False
                    else f"{source_label}刊登未揭露，需向出租方確認"
                ),
            )
        )

    if property_.floor is None:
        floor_status = "unknown"
        floor_evidence = f"{source_label}刊登未揭露所在樓層"
    elif property_.has_elevator is True:
        floor_status = "met"
        floor_evidence = f"位於 {property_.floor} 樓且有電梯"
    elif property_.floor <= req.max_floor_without_elevator:
        floor_status = "met"
        floor_evidence = (
            f"位於 {property_.floor} 樓，不超過可接受的 "
            f"{req.max_floor_without_elevator} 樓"
        )
    elif property_.has_elevator is False:
        floor_status = "unmet"
        floor_evidence = (
            f"{property_.floor} 樓無電梯，超過可接受的 "
            f"{req.max_floor_without_elevator} 樓"
        )
    else:
        floor_status = "unknown"
        floor_evidence = (
            f"位於 {property_.floor} 樓，但刊登未揭露是否有電梯"
        )
    checks.append(
        ConditionCheck(
            label="樓層負擔",
            status=floor_status,
            evidence=floor_evidence,
        )
    )

    if req.noise_preference != "no_preference":
        if property_.noise_level is None:
            noise_status = "unknown"
            noise_evidence = "刊登未揭露安靜程度，需實地確認"
        elif req.noise_preference == "quiet":
            noise_status = (
                "met" if property_.noise_level == "low" else "unmet"
            )
            noise_evidence = {
                "low": "現有刊登證據顯示環境安靜",
                "medium": "現有刊登證據顯示可能偶爾有噪音",
                "high": "現有刊登證據顯示環境較吵",
            }[property_.noise_level]
        else:
            noise_status = (
                "met"
                if property_.noise_level in {"low", "medium"}
                else "unmet"
            )
            noise_evidence = {
                "low": "現有刊登證據顯示環境安靜",
                "medium": "現有刊登證據顯示一般住宅噪音程度",
                "high": "現有刊登證據顯示環境較吵",
            }[property_.noise_level]
        if property_.noise_analyzed_by_ai and property_.noise_evidence:
            noise_evidence = (
                f"AI 語意判讀刊登原文：{property_.noise_evidence}"
                f"（可信度 {property_.noise_confidence}）"
            )
        checks.append(
            ConditionCheck(
                label="安靜程度",
                status=noise_status,
                evidence=noise_evidence,
            )
        )

    searchable = " ".join(
        [
            property_.title,
            property_.description,
            *property_.features,
            property_.vision_summary,
            property_.listing_text,
        ]
    )
    for preference in req.preferences:
        if not preference:
            continue
        is_space_preference = any(
            term in preference for term in ("空間大", "寬敞", "坪數大")
        )
        if is_space_preference and property_.vision_analyzed_by_ai:
            status = (
                "met"
                if property_.space_impression == "spacious"
                else "unmet"
                if property_.space_impression == "compact"
                else "unknown"
            )
            checks.append(
                ConditionCheck(
                    label=preference,
                    status=status,
                    evidence=(
                        f"AI 綜合刊登"
                        f"{f' {property_.listing_area_ping:g} 坪' if property_.listing_area_ping is not None else '坪數'}"
                        f"與照片判讀：{property_.vision_summary}"
                        f"（可信度 {property_.vision_confidence}）"
                    ),
                )
            )
            continue
        preference_terms = {
            "採光良好": ("採光", "明亮", "大窗"),
            "可開伙": ("可開伙", "開伙", "廚房"),
            "可養貓": ("可養貓", "可養寵物", "寵物友善"),
            "可養寵物": ("可養貓", "可養狗", "可養寵物", "寵物友善"),
            "隔音良好": ("隔音佳", "隔音良好", "氣密窗"),
        }.get(preference, (preference,))
        negative_terms = (
            (
                "不可養",
                "不可寵物",
                "不可寵",
                "禁養",
                "禁寵",
                "禁止寵物",
                "禁止飼養",
                "不得飼養",
                "謝絕寵物",
            )
            if "養貓" in preference or "寵物" in preference
            else ("隔音差", "隔音不好")
            if "隔音" in preference
            else ()
        )
        contradicted = any(term in searchable for term in negative_terms)
        matched = any(term in searchable for term in preference_terms)
        status = "unmet" if contradicted else "met" if matched else "unknown"
        checks.append(
            ConditionCheck(
                label=preference,
                status=status,
                evidence=(
                    f"{source_label}刊登文字明確顯示此條件不符合"
                    if contradicted
                    else
                    f"{source_label}刊登文字或標籤有提到此條件"
                    if matched
                    else f"{source_label}刊登未提及，不代表一定不符合"
                ),
            )
        )

    check_indexes = {check.label: index for index, check in enumerate(checks)}
    for ai_check in property_.listing_requirement_checks:
        ai_evidence = (
            f"AI 語意判讀刊登原文：{ai_check.evidence}"
            f"（可信度 {ai_check.confidence}）"
        )
        replacement = ConditionCheck(
            label=ai_check.label,
            status=ai_check.status,
            evidence=ai_evidence,
        )
        existing_index = check_indexes.get(ai_check.label)
        reliable = (
            ai_check.confidence in {"medium", "high"}
            and ai_check.status in {"met", "unmet"}
        )
        if existing_index is None:
            checks.append(replacement)
            check_indexes[ai_check.label] = len(checks) - 1
        elif reliable or checks[existing_index].status == "unknown":
            checks[existing_index] = replacement

    met_count = sum(check.status == "met" for check in checks)
    unmet_count = sum(check.status == "unmet" for check in checks)
    unknown_count = sum(check.status == "unknown" for check in checks)
    total_count = met_count + unmet_count + unknown_count
    known_count = met_count + unmet_count
    known_match_rate = (
        met_count / known_count * 100
        if known_count
        else 0
    )
    data_completeness = (
        round(known_count / total_count * 100)
        if total_count
        else 0
    )
    score = known_match_rate

    for check in checks:
        if check.status == "met":
            positives.append(f"{check.label}符合")
        elif check.status == "unmet":
            concerns.append(f"{check.label}不符合：{check.evidence}")
        elif check.status == "unknown":
            concerns.append(f"{check.label}待確認")
    concerns.extend(property_.risks[:2])
    if property_.vision_analyzed_by_ai:
        space_label = {
            "spacious": "寬敞",
            "adequate": "大小適中",
            "compact": "較緊湊",
            "unknown": "無法判讀",
        }[property_.space_impression]
        positives.append(
            f"AI 圖片分析：空間觀感{space_label}"
            f"（刊登 {property_.listing_area_ping:g} 坪）"
            if property_.listing_area_ping is not None
            else f"AI 圖片分析：空間觀感{space_label}"
        )
        if property_.vision_confidence == "low":
            concerns.append("圖片數量或清晰度不足，AI 空間判讀可信度低")

    return AgentAssessment(
        agent="Property Agent",
        property_id=property_.id,
        score=_clamp(score),
        summary=(
            f"{met_count} 項符合、{unknown_count} 項待確認、"
            f"{unmet_count} 項不符合。"
            + (
                f" AI 已分析刊登圖片（可信度 {property_.vision_confidence}）。"
                if property_.vision_analyzed_by_ai
                else ""
            )
            + (
                " AI 已語意判讀完整刊登文字。"
                if property_.listing_requirements_analyzed_by_ai
                else ""
            )
        ),
        positives=list(dict.fromkeys(positives)),
        concerns=list(dict.fromkeys(concerns)),
        metrics={
            "met_count": met_count,
            "unmet_count": unmet_count,
            "unknown_count": unknown_count,
            "condition_count": total_count,
            "known_match_rate": round(known_match_rate),
            "data_completeness": data_completeness,
            "score_available": known_count > 0,
            "formula_version": "RentWise Scoring v1.3",
            "ai_used": (
                property_.vision_analyzed_by_ai
                or property_.listing_requirements_analyzed_by_ai
            ),
            "ai_confidence": (
                property_.vision_confidence
                or (
                    "medium"
                    if property_.listing_requirements_analyzed_by_ai
                    else "not_used"
                )
            ),
            "listing_text_source": property_.listing_text_source,
            "listing_requirements_analyzed_by_ai": (
                property_.listing_requirements_analyzed_by_ai
            ),
            "space_impression": property_.space_impression,
            "listing_area_ping": (
                property_.listing_area_ping
                if property_.listing_area_ping is not None
                else "unknown"
            ),
        },
        checks=checks,
    )


def suitability_assessment(
    property_: Property,
    req: UserRequirements,
    location: AgentAssessment,
    cost: AgentAssessment,
    property_result: AgentAssessment,
) -> AgentAssessment:
    raw_weights = req.weights
    positives, concerns = [], []

    original_weights = {
        "location": raw_weights.location,
        "cost": raw_weights.cost,
        "property": raw_weights.property,
    }
    available = {
        "location": bool(location.metrics.get("score_available", True)),
        "cost": bool(cost.metrics.get("score_available", True)),
        "property": bool(property_result.metrics.get("score_available", True)),
    }
    active_total = sum(
        value
        for name, value in original_weights.items()
        if available[name] and value > 0
    )
    weights = {
        name: (
            value / active_total
            if available[name] and active_total > 0
            else 0
        )
        for name, value in original_weights.items()
    }
    scores = {
        "location": location.score,
        "cost": cost.score,
        "property": property_result.score,
    }
    contributions = {
        name: scores[name] * weights[name]
        for name in scores
    }
    total = sum(contributions.values())
    original_total = sum(original_weights.values())
    evidence_coverage = (
        active_total / original_total * 100 if original_total else 0
    )

    hard_conflicts = []
    if req.needs_window and property_.has_window is False:
        hard_conflicts.append("對外窗")
    if req.needs_elevator and property_.has_elevator is False:
        hard_conflicts.append("電梯")
    if req.needs_rental_subsidy and property_.rental_subsidy_eligible is False:
        hard_conflicts.append("租金補貼")
    if (
        property_.floor is not None
        and property_.has_elevator is False
        and property_.floor > req.max_floor_without_elevator
    ):
        hard_conflicts.append("無電梯樓層上限")
    if hard_conflicts:
        concerns.append("必要條件衝突：" + "、".join(hard_conflicts))

    qualified = not hard_conflicts
    return AgentAssessment(
        agent="Suitability Agent",
        property_id=property_.id,
        score=_clamp(total),
        summary=(
            "依可取得資料重新分配使用者權重並完成適配計算。"
            if qualified
            else "分數僅供比較；此房源明確違反必要條件，不列為合格推薦。"
        ),
        positives=positives,
        concerns=concerns,
        metrics={
            "location_weight": round(weights["location"], 3),
            "cost_weight": round(weights["cost"], 3),
            "property_weight": round(weights["property"], 3),
            "original_location_weight": round(
                raw_weights.location / original_total, 3
            ),
            "original_cost_weight": round(raw_weights.cost / original_total, 3),
            "original_property_weight": round(
                raw_weights.property / original_total, 3
            ),
            "location_contribution": round(contributions["location"], 1),
            "cost_contribution": round(contributions["cost"], 1),
            "property_contribution": round(contributions["property"], 1),
            "location_available": available["location"],
            "cost_available": available["cost"],
            "property_available": available["property"],
            "qualified": qualified,
            "disqualifying_conflicts": "、".join(hard_conflicts),
            "evidence_coverage_percent": round(evidence_coverage),
            "formula_version": "RentWise Scoring v1.3",
            "noise_level": property_.noise_level or "unknown",
            "noise_evidence_source": (
                "property_agent_openai"
                if property_.noise_analyzed_by_ai
                else "listing_rules"
                if property_.noise_level is not None
                else "unknown"
            ),
            "noise_evidence": property_.noise_evidence or "未取得明確刊登證據",
            "noise_confidence": property_.noise_confidence or "not_used",
        },
    )
