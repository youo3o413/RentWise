import re

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
    amenity_source = "周邊設施資料" if property_.nearby_data_source == "mock" else "OpenStreetMap"
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
                f"{amenity_source}顯示最近便利商店約 "
                f"{property_.nearest_convenience_store_meters} 公尺"
            )
        else:
            positives.append("步行生活圈包含便利商店")
    elif req.needs_convenience_store and store_available:
        concerns.append(f"{amenity_source}在 500 公尺內未找到便利商店")
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
            concerns.append(f"{amenity_source}未找到 500 公尺內停車場")
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


PET_SPECIES = (
    "貓", "狗", "烏龜", "陸龜", "水龜", "兔", "倉鼠", "天竺鼠", "鼠",
    "鸚鵡", "鳥", "魚", "蛇", "蜥蜴", "守宮", "刺蝟", "蜜袋鼯", "爬蟲",
)
PET_WORDS = "|".join(("寵物", "毛孩", "毛小孩", "犬", *PET_SPECIES))


def _is_pet_preference(preference: str) -> bool:
    return bool(re.search(PET_WORDS, preference)) and not bool(
        re.search(r"不養|不飼養|沒有|無寵|不需要|無需|不可|不能|不允許|禁止|不得|謝絕|禁養|禁寵", preference)
    )


def _policy_preference_check(
    preference: str, text: str, source_label: str
) -> ConditionCheck | None:
    """Keep explicit bans and conditional permissions out of positive matches."""
    compact = re.sub(r"[ \t]+", "", text).replace("犬", "狗")
    status = "unknown"
    evidence = "刊登未明確允許此條件，需向出租方確認"
    deny = r"(?:不可|不能|不准|不允許|禁止|不得|謝絕|不接受)(?:飼養|養)?"

    if _is_pet_preference(preference):
        requested = preference.replace("犬", "狗")
        # Prefer the AI's canonical species label, including less common pets.
        canonical = re.search(r"寵物[（(]([^）)]+)[）)]", requested)
        if canonical:
            species = []
            for label in re.split(r"[、,，]", canonical.group(1)):
                label = label.strip()
                if label:
                    matches = [animal for animal in PET_SPECIES if animal in label]
                    species.extend(matches or [re.escape(label)])
        else:
            species = [animal for animal in PET_SPECIES if animal in requested]
        # Avoid treating 倉鼠 and 鼠 as two separate requested pets.
        species = [animal for animal in species if not any(animal != other and animal in other for other in species)]
        species_words = "|".join(species) or PET_WORDS
        pet_clauses = "；".join(
            clause
            for clause in re.split(r"[。；;\n]", compact)
            if re.search(rf"寵|{PET_WORDS}|{species_words}", clause)
        )
        general_ban = re.search(
            rf"{deny}(?:寵物|毛孩|毛小孩)|禁寵|禁養(?=寵物|[，,。；;\s]|$)(?:寵物)?",
            pet_clauses,
        )
        species_ban = any(
            re.search(rf"{deny}(?:任何)?{animal}|禁養{animal}|{animal}(?:隻)?不接受", pet_clauses)
            for animal in species
        )
        cats_only = bool(re.search(r"(?:只|僅)(?:接受|允許|限|能|可)?(?:飼養|養)?貓", pet_clauses))
        dogs_only = bool(re.search(r"(?:只|僅)(?:接受|允許|限|能|可)?(?:飼養|養)?(?:小型)?狗", pet_clauses))
        restricted_species = (cats_only and any(animal != "貓" for animal in species)) or (dogs_only and any(animal != "狗" for animal in species))
        small_dogs_only = bool(re.search(r"(?:限|僅|只|可養)小型狗", pet_clauses))
        conditional = bool(re.search(
            r"可談|需談|另議|面議|待確認|需確認|請先詢問|"
            r"(?:需|須|事先).{0,12}(?:同意|確認|審核|討論)|"
            r"(?:限|最多|至多|接受)[一二三四五\d]+(?:至[一二三四五\d]+)?隻|"
            r"(?:需|須).{0,4}(?:另簽|加收|另付)|"
            r"視.{0,6}情況|依.{0,6}個案",
            pet_clauses,
        ))
        limited_generic = not species and bool(re.search(
            r"限|需|須|不接受|不可|禁止", pet_clauses
        ))
        size_unverified = small_dogs_only and "狗" in species and "小型" not in requested
        if general_ban or species_ban or restricted_species:
            status = "unmet"
            evidence = "刊登明確禁止飼養所需寵物，此條件不符合"
        elif conditional or limited_generic or size_unverified:
            evidence = "寵物規定附有種類、體型、數量或房東同意條件，需確認"
        else:
            general_permission = bool(re.search(
                r"可(?:以)?(?:飼養|養)?寵物|寵物友善|接受寵物|可寵", pet_clauses
            ))
            species_permission = bool(species) and all(
                re.search(rf"(?:可(?:以)?(?:飼養|養)?|允許(?:飼養|養)?|接受|限)(?:小型)?{animal}", pet_clauses)
                for animal in species
            )
            community_only = "社區" in pet_clauses and not re.search(r"房東|出租方", pet_clauses)
            if (general_permission or species_permission) and not community_only:
                status = "met"
                evidence = "刊登明確允許飼養所需寵物"
    elif "開伙" in preference and not re.search(r"不開伙|不需要|無需", preference):
        if re.search(r"(?:不可|不能|禁止|不得|不允許)開伙|禁開伙", compact):
            status = "unmet"
            evidence = "刊登明確禁止開伙，此條件不符合"
        elif re.search(r"開伙.{0,8}(?:可談|另議|需確認)|(?:限|僅可|只能).{0,6}(?:電磁爐|電鍋|簡炊)|不可明火", compact):
            evidence = "開伙方式有限制或需出租方同意，需確認"
        elif re.search(r"可開伙|廚房", compact):
            status = "met"
            evidence = "刊登文字明確提及可開伙或廚房"
    else:
        return None
    return ConditionCheck(label=preference, status=status, evidence=f"{source_label}{evidence}")


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

    searchable = "\n".join(
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
        policy_check = _policy_preference_check(preference, searchable, source_label)
        if policy_check is not None:
            checks.append(policy_check)
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
            "隔音良好": ("隔音佳", "隔音良好", "氣密窗"),
        }.get(preference, (preference,))
        negative_terms = (
            ("隔音差", "隔音不好")
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
    pending_conditions = []
    estimated_monthly_cost = cost.metrics.get("estimated_monthly_cost")
    if (
        isinstance(estimated_monthly_cost, (int, float))
        and estimated_monthly_cost > req.budget
    ):
        hard_conflicts.append("每月總預算")
    if req.needs_window and property_.has_window is False:
        hard_conflicts.append("對外窗")
    elif req.needs_window and property_.has_window is None:
        pending_conditions.append("對外窗")
    if req.needs_elevator and property_.has_elevator is False:
        hard_conflicts.append("電梯")
    elif req.needs_elevator and property_.has_elevator is None:
        pending_conditions.append("電梯")
    if req.needs_rental_subsidy and property_.rental_subsidy_eligible is False:
        hard_conflicts.append("租金補貼")
    elif req.needs_rental_subsidy and property_.rental_subsidy_eligible is None:
        pending_conditions.append("租金補貼")
    if req.needs_convenience_store:
        if property_.nearby_convenience_store_count == 0:
            hard_conflicts.append("附近便利商店")
        elif property_.nearby_convenience_store_count is None:
            pending_conditions.append("附近便利商店")
    if req.needs_parking:
        if property_.nearby_parking_count == 0:
            hard_conflicts.append("附近停車場")
        elif property_.nearby_parking_count is None:
            pending_conditions.append("附近停車場")
    if (
        property_.floor is not None
        and property_.has_elevator is False
        and property_.floor > req.max_floor_without_elevator
    ):
        hard_conflicts.append("無電梯樓層上限")
    if (
        property_.commute_minutes is not None
        and property_.commute_minutes > req.max_commute_minutes
    ):
        hard_conflicts.append("通勤時間上限")
    commute_unverified = property_.commute_minutes is None
    if commute_unverified:
        pending_conditions.append("通勤時間")
        concerns.append("地址或通勤路線無法驗證，不列為合格首選")
    for check in property_result.checks:
        if check.label not in req.preferences:
            continue
        if not (_is_pet_preference(check.label) or "開伙" in check.label):
            continue
        if check.status == "unmet":
            hard_conflicts.append(check.label)
        elif check.status == "unknown":
            pending_conditions.append(check.label)
    if hard_conflicts:
        concerns.append("必要條件衝突：" + "、".join(hard_conflicts))
    pending_conditions = list(dict.fromkeys(pending_conditions))
    if pending_conditions:
        concerns.append("必要條件待確認：" + "、".join(pending_conditions))

    qualification_status = (
        "needs_verification"
        if hard_conflicts or pending_conditions
        else "qualified"
    )
    qualified = qualification_status == "qualified"
    return AgentAssessment(
        agent="Suitability Agent",
        property_id=property_.id,
        score=_clamp(total),
        summary=(
            "必要條件皆有證據符合，並已完成透明適配計算。"
            if qualification_status == "qualified"
            else "仍有必要條件或風險需要使用者進一步確認。"
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
            "qualification_status": qualification_status,
            "pending_conditions": "、".join(pending_conditions),
            "disqualifying_conflicts": (
                "、".join(hard_conflicts)
                if hard_conflicts
                else ""
            ),
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
