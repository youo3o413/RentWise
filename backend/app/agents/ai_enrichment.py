import json
from typing import Literal

from openai import OpenAI, OpenAIError, RateLimitError
from pydantic import BaseModel, Field

from app.config import get_settings
from app.models.schemas import Property, UserRequirements


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


def analyze_property_images(
    properties: list[Property],
) -> tuple[dict[str, PropertyVisionItem], str]:
    candidates = [
        item
        for item in properties
        if item.image_url.startswith("http")
        and "images.unsplash.com" not in item.image_url
    ]
    if not candidates:
        return {}, "沒有可供 AI 判讀的實際刊登圖片"
    settings = get_settings()
    if not settings.openai_api_key:
        return {}, "未設定 OpenAI API Key，略過房源圖片判讀"

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
        content.extend(
            [
                {
                    "type": "input_text",
                    "text": (
                        f"property_id={item.id}；標題={item.title}；"
                        f"刊登坪數={item.listing_area_ping or '未揭露'}；"
                        f"刊登設備={'、'.join(item.features) or '未揭露'}"
                    ),
                },
                {
                    "type": "input_image",
                    "image_url": item.image_url,
                    "detail": "high",
                },
            ]
        )
    try:
        response = OpenAI(api_key=settings.openai_api_key).responses.parse(
            model=settings.openai_model,
            input=[{"role": "user", "content": content}],
            text_format=PropertyVisionBatch,
            max_output_tokens=1800,
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
