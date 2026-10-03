import json
from typing import Literal

from openai import OpenAI, OpenAIError, RateLimitError
from pydantic import BaseModel, Field

from app.config import get_settings
from app.services.listing_photo_service import vision_image_url
from app.models.schemas import (
    ListingRequirementEvidence,
    Property,
    UserRequirements,
)


class CostEstimateItem(BaseModel):
    property_id: str
    management_fee: int = Field(ge=0, le=20000)
    water_fee: int = Field(ge=0, le=5000)
    electricity_rate: float = Field(ge=0, le=20)
    estimated_kwh: int = Field(ge=0, le=1500)
    confidence: Literal["low", "medium", "high"]
    basis: list[str]


class CostEstimateBatch(BaseModel):
    estimates: list[CostEstimateItem]


class PropertyVisionItem(BaseModel):
    property_id: str
    visible_window: bool
    window_description: str
    space_impression: Literal["spacious", "adequate", "compact", "unknown"]
    summary: str
    confidence: Literal["low", "medium", "high"]


class PropertyVisionBatch(BaseModel):
    analyses: list[PropertyVisionItem]


class ListingRequirementCheckItem(BaseModel):
    label: str
    status: Literal["met", "unmet", "unknown"]
    evidence: str
    confidence: Literal["low", "medium", "high"]


class ListingRequirementItem(BaseModel):
    property_id: str
    summary: str
    checks: list[ListingRequirementCheckItem]
    noise_assessment_performed: bool = False
    noise_level: Literal["low", "medium", "high", "unknown"] = "unknown"
    noise_evidence: str = ""
    noise_confidence: Literal["low", "medium", "high"] = "low"


class ListingRequirementBatch(BaseModel):
    analyses: list[ListingRequirementItem]


class ListingUseItem(BaseModel):
    property_id: str
    classification: Literal["habitable", "not_habitable", "uncertain"]
    property_type: str
    evidence: str
    confidence: Literal["low", "medium", "high"]


class ListingUseBatch(BaseModel):
    analyses: list[ListingUseItem]


def _quota_message(exc: RateLimitError, agent: str) -> str:
    if getattr(exc, "code", None) == "insufficient_quota":
        return f"{agent} 的 OpenAI API 額度不足，改用透明規則"
    return f"{agent} 的 OpenAI 搜尋頻率受限，改用透明規則"


def estimate_property_costs(
    req: UserRequirements,
    properties: list[Property],
) -> tuple[dict[str, CostEstimateItem], str]:
    candidates = [
        property_
        for property_ in properties
        if not (
            property_.management_fee_disclosed
            and property_.water_fee_disclosed
            and property_.electricity_rate_disclosed
            and property_.electricity_usage_disclosed
        )
    ]
    if not candidates:
        return {}, "刊登費用皆已揭露，不需 AI 補估"
    settings = get_settings()
    if not settings.openai_api_key:
        return {}, "未設定 OpenAI API Key，費用缺漏改用透明規則估算"

    payload = [
        {
            "property_id": item.id,
            "title": item.title,
            "address": item.address,
            "rent": item.rent,
            "listing_area_ping": item.listing_area_ping,
            "features": item.features,
            "description": item.description,
            "disclosed": {
                "management_fee": (
                    item.management_fee if item.management_fee_disclosed else None
                ),
                "water_fee": item.water_fee if item.water_fee_disclosed else None,
                "electricity_rate": (
                    item.electricity_rate
                    if item.electricity_rate_disclosed
                    else None
                ),
                "estimated_kwh": (
                    item.estimated_kwh
                    if item.electricity_usage_disclosed
                    else None
                ),
            },
        }
        for item in candidates
    ]
    instructions = """
你是台灣租屋 Cost Agent。請利用公開搜尋與房源所在地，補估刊登未揭露的管理費、
每月水費、每度電價與每月用電量。已揭露的數字必須原樣保留。估算需考量縣市、
房型、坪數與一般住宅用電情境；不要把房東未揭露的電價宣稱為事實。
basis 每項都要簡短說明資料或假設，confidence 反映地址、坪數與公開資料是否充足。
只回傳輸入中的 property_id，所有金額使用新台幣。
""".strip()
    try:
        response = OpenAI(api_key=settings.openai_api_key).responses.parse(
            model=settings.openai_model,
            instructions=instructions,
            input=json.dumps(
                {
                    "destination": req.destination,
                    "properties": payload,
                },
                ensure_ascii=False,
            ),
            tools=[
                {
                    "type": "web_search",
                    "search_context_size": "low",
                }
            ],
            text_format=CostEstimateBatch,
            max_output_tokens=1800,
            timeout=35,
        )
        parsed = response.output_parsed
        if not parsed:
            return {}, "Cost Agent 未取得可用 AI 結構化結果，改用透明規則"
        allowed = {item.id for item in candidates}
        estimates = {
            item.property_id: item
            for item in parsed.estimates
            if item.property_id in allowed
        }
        return estimates, f"AI 已依所在地與房型補估 {len(estimates)} 筆未揭露費用"
    except RateLimitError as exc:
        return {}, _quota_message(exc, "Cost Agent")
    except (OpenAIError, ValueError, TypeError):
        return {}, "Cost Agent 的 AI 費用估算暫時無法使用，改用透明規則"


def apply_cost_estimate(
    property_: Property,
    estimate: CostEstimateItem | None,
) -> Property:
    if estimate is None:
        return property_
    return property_.model_copy(
        update={
            "management_fee": (
                property_.management_fee
                if property_.management_fee_disclosed
                else estimate.management_fee
            ),
            "water_fee": (
                property_.water_fee
                if property_.water_fee_disclosed
                else estimate.water_fee
            ),
            "electricity_rate": (
                property_.electricity_rate
                if property_.electricity_rate_disclosed
                else estimate.electricity_rate
            ),
            "estimated_kwh": (
                property_.estimated_kwh
                if property_.electricity_usage_disclosed
                else estimate.estimated_kwh
            ),
            "cost_estimated_by_ai": True,
            "cost_estimate_confidence": estimate.confidence,
            "cost_estimate_basis": estimate.basis,
        }
    )


def classify_listing_uses(
    properties: list[Property],
) -> tuple[dict[str, ListingUseItem], str]:
    candidates = [item for item in properties if item.listing_text.strip()]
    if not candidates:
        return {}, "沒有可供 AI 判讀用途的刊登文字"
    settings = get_settings()
    if not settings.openai_api_key:
        return {}, "未設定 OpenAI API Key，房源用途改用透明規則篩選"
    payload = [
        {
            "property_id": item.id,
            "title": item.title,
            "source": item.source_name,
            "listing_text": item.listing_text[:12000],
        }
        for item in candidates
    ]
    instructions = """
你是台灣租屋平台的房源用途審核 Agent。請只依提供的標題與原始刊登頁文字，
判斷物件是否真的是可供人長期居住的住宅。

- habitable：套房、雅房、整層住家、公寓、住宅等，可合理確認供人居住。
- not_habitable：純車位、置物空間、儲藏室、迷你倉、倉庫、土地、純店面、
  純辦公室，或明寫禁止居住／過夜。
- uncertain：頁面證據不足或用途混合，無法安全確認。

住宅「附車位／附儲藏室」仍是 habitable，不可因附屬設施誤刪。evidence 必須引用
或極短忠實轉述刊登原文，禁止用價格、照片風格或常識猜測。不得產生任何分數。
""".strip()
    try:
        response = OpenAI(api_key=settings.openai_api_key).responses.parse(
            model=settings.openai_model,
            instructions=instructions,
            input=json.dumps({"properties": payload}, ensure_ascii=False),
            text_format=ListingUseBatch,
            max_output_tokens=1800,
            timeout=35,
        )
        parsed = response.output_parsed
        if not parsed:
            return {}, "房源用途 AI 未取得可用的結構化結果"
        allowed = {item.id for item in candidates}
        analyses = {
            item.property_id: item
            for item in parsed.analyses
            if item.property_id in allowed
        }
        rejected = sum(
            item.classification == "not_habitable"
            and item.confidence in {"medium", "high"}
            for item in analyses.values()
        )
        return analyses, f"AI 已檢查房源用途，排除 {rejected} 筆明確非住宅"
    except RateLimitError as exc:
        return {}, _quota_message(exc, "房源用途審核 Agent")
    except (OpenAIError, ValueError, TypeError):
        return {}, "房源用途 AI 暫時無法使用，改用透明規則篩選"


def interpret_listing_requirements(
    req: UserRequirements,
    properties: list[Property],
) -> tuple[dict[str, ListingRequirementItem], str]:
    labels = []
    if req.needs_window:
        labels.append("對外窗")
    if req.needs_elevator:
        labels.append("電梯")
    if req.needs_rental_subsidy:
        labels.append("租金補貼")
    labels.extend(req.preferences)
    labels = list(dict.fromkeys(label for label in labels if label))
    noise_requested = req.noise_preference != "no_preference"
    candidates = [item for item in properties if item.listing_text.strip()]
    if not labels and not noise_requested:
        return {}, "使用者沒有需要刊登頁語意判讀的房屋條件"
    if not candidates:
        return {}, "租屋平台未提供可供 AI 判讀的刊登文字"
    settings = get_settings()
    if not settings.openai_api_key:
        return {}, "未設定 OpenAI API Key，房屋條件改用透明關鍵字規則"

    payload = [
        {
            "property_id": item.id,
            "source": item.source_name,
            "page_source": item.listing_text_source,
            "requirements": labels,
            "noise_assessment_requested": noise_requested,
            "listing_text": item.listing_text[:12000],
        }
        for item in candidates
    ]
    instructions = """
你是台灣租屋 Property Agent。請只根據提供的原始租屋刊登頁文字，逐項判斷使用者
條件是否符合。你必須理解同義、口語、縮寫與委婉語句，例如「禁寵／不可寵物」
代表不可養貓，「毛孩可談」不等於明確允許，「可報稅／300億租金補貼」可支持
租金補貼。否定語句優先於正面關鍵字。
寵物包括烏龜、兔子、鼠、鳥、魚、爬蟲及其他飼養動物，不限貓狗。
須保留並核對需求中的種類；「可養貓」不能作為允許烏龜的證據，僅允許某種動物
不能滿足其他種類的需求。未說明其他種類是否接受時標為 unknown。

每個 property_id 必須回傳每一個輸入 requirement，label 必須原樣保留：
- met：刊登文字有明確證據符合。
- unmet：刊登文字有明確證據不符合。
- unknown：沒有證據、語意模糊、需詢問房東，或只能從常識猜測。

evidence 必須引用或極短忠實轉述實際刊登語句並解釋；不得捏造頁面沒有的內容。
照片沒拍到、刊登沒寫，都不能判為不符合。社區可養寵物也不能代替房東允許。
summary 簡短說明本次判讀，禁止自行產生分數。

若 noise_assessment_requested=true，另根據刊登原文產生 noise_level：
- low：原文明確表示安靜、清幽、寧靜、遠離車流等。
- medium：原文同時存在安靜與可能噪音證據，或只表示一般住宅環境。
- high：原文明確表示臨主要道路、夜市、酒吧、施工或其他明顯噪音來源。
- unknown：沒有直接證據，不能只因樓層、行政區或生活機能自行猜測。
noise_evidence 必須忠實引用或轉述原文；noise_confidence 反映證據強度。
noise_assessment_performed 必須與 noise_assessment_requested 相同；若沒有要求，
noise_level 必須為 unknown，noise_evidence 必須為空字串。
""".strip()
    try:
        response = OpenAI(api_key=settings.openai_api_key).responses.parse(
            model=settings.openai_model,
            instructions=instructions,
            input=json.dumps({"properties": payload}, ensure_ascii=False),
            text_format=ListingRequirementBatch,
            max_output_tokens=3200,
            timeout=40,
        )
        parsed = response.output_parsed
        if not parsed:
            return {}, "Property Agent 未取得可用的刊登頁結構化判讀"
        allowed = {item.id for item in candidates}
        analyses = {
            item.property_id: item
            for item in parsed.analyses
            if item.property_id in allowed
        }
        return analyses, f"AI 已語意判讀 {len(analyses)} 筆完整刊登文字"
    except RateLimitError as exc:
        return {}, _quota_message(exc, "Property Agent")
    except (OpenAIError, ValueError, TypeError):
        return {}, "Property Agent 的刊登頁 AI 判讀暫時無法使用，改用透明規則"


def apply_listing_requirement_analysis(
    property_: Property,
    analysis: ListingRequirementItem | None,
) -> Property:
    if analysis is None:
        return property_
    checks = [
        ListingRequirementEvidence(
            label=check.label,
            status=check.status,
            evidence=check.evidence,
            confidence=check.confidence,
        )
        for check in analysis.checks
    ]
    reliable = {
        check.label: check.status
        for check in checks
        if check.confidence in {"medium", "high"}
        and check.status in {"met", "unmet"}
    }
    updates = {
        "listing_requirements_analyzed_by_ai": True,
        "listing_requirement_summary": analysis.summary,
        "listing_requirement_checks": checks,
        "noise_analyzed_by_ai": analysis.noise_assessment_performed,
        "noise_evidence": (
            analysis.noise_evidence
            if analysis.noise_assessment_performed
            else property_.noise_evidence
        ),
        "noise_confidence": (
            analysis.noise_confidence
            if analysis.noise_assessment_performed
            else property_.noise_confidence
        ),
    }
    if "對外窗" in reliable:
        updates["has_window"] = reliable["對外窗"] == "met"
        updates["window_type"] = "AI 語意判讀刊登文字"
    if "電梯" in reliable:
        updates["has_elevator"] = reliable["電梯"] == "met"
    if "租金補貼" in reliable:
        updates["rental_subsidy_eligible"] = reliable["租金補貼"] == "met"
    if (
        analysis.noise_assessment_performed
        and analysis.noise_level in {"low", "medium", "high"}
        and analysis.noise_confidence in {"medium", "high"}
    ):
        updates["noise_level"] = analysis.noise_level
    return property_.model_copy(update=updates)


def analyze_property_images(
    properties: list[Property],
) -> tuple[dict[str, PropertyVisionItem], str]:
    settings = get_settings()
    if not settings.openai_api_key:
        return {}, "未設定 OpenAI API Key，略過房源圖片判讀"
    images_by_id = {
        item.id: [
            resolved
            for image in dict.fromkeys([item.image_url, *item.image_urls])
            if (resolved := vision_image_url(image))
        ][:4]
        for item in properties
    }
    candidates = [item for item in properties if images_by_id[item.id]]
    if not candidates:
        return {}, "沒有可供 AI 判讀的房源圖片"

    content: list[dict[str, str]] = [
        {
            "type": "input_text",
            "text": (
                "你是台灣租屋 Property Agent。以下每組文字後面緊接該房源圖片。"
                "請判斷照片是否清楚看到窗戶，並把照片觀感與刊登坪數一起分析空間。"
                "沒有拍到窗戶不等於房屋沒有窗戶；縮圖、廣角鏡與照片數不足時必須"
                "降低 confidence。禁止從照片推斷精確面積，只能依已提供坪數描述"
                " spacious、adequate、compact 或 unknown。"
            ),
        }
    ]
    for item in candidates:
        content.append(
            {
                "type": "input_text",
                "text": (
                    f"property_id={item.id}；標題={item.title}；"
                    f"刊登坪數={item.listing_area_ping or '未揭露'}；"
                    f"刊登設備={'、'.join(item.features) or '未揭露'}"
                ),
            }
        )
        content.extend(
            {
                "type": "input_image",
                "image_url": image,
                "detail": "low",
            }
            for image in images_by_id[item.id]
        )
    try:
        response = OpenAI(api_key=settings.openai_api_key).responses.parse(
            model=settings.openai_model,
            input=[{"role": "user", "content": content}],
            text_format=PropertyVisionBatch,
            max_output_tokens=max(1800, len(candidates) * 300),
            timeout=40,
        )
        parsed = response.output_parsed
        if not parsed:
            return {}, "Property Agent 未取得可用 AI 圖片結果"
        allowed = {item.id for item in candidates}
        analyses = {
            item.property_id: item
            for item in parsed.analyses
            if item.property_id in allowed
        }
        return analyses, f"AI 已分析 {len(analyses)} 筆房源圖片的窗戶與空間"
    except RateLimitError as exc:
        return {}, _quota_message(exc, "Property Agent")
    except (OpenAIError, ValueError, TypeError):
        return {}, "Property Agent 的 AI 圖片判讀暫時無法使用"


def apply_property_vision(
    property_: Property,
    analysis: PropertyVisionItem | None,
) -> Property:
    if analysis is None:
        return property_
    window_confirmed = property_.has_window is True or analysis.visible_window
    return property_.model_copy(
        update={
            "has_window": True if window_confirmed else property_.has_window,
            "window_type": (
                analysis.window_description
                if analysis.visible_window and property_.has_window is not True
                else property_.window_type
            ),
            "vision_analyzed_by_ai": True,
            "vision_window_visible": analysis.visible_window,
            "vision_confidence": analysis.confidence,
            "vision_summary": analysis.summary,
            "space_impression": analysis.space_impression,
        }
    )
