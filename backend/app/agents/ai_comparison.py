import json
from typing import Any

from app.config import get_settings
from app.models.schemas import UserRequirements


def build_rule_summary(ranked: list[dict[str, Any]]) -> str:
    best = ranked[0]
    property_ = best["property"]
    return (
        f"綜合多個 Agent 的分析，首選為「{property_.title}」，"
        f"適配分數 {best['total_score']:.1f} 分，預估每月支出 "
        f"{best['estimated_monthly_cost']:,} 元。此排名同時考量通勤、"
        "真實生活成本、房況硬體與個人生活偏好；建議簽約前仍實地確認"
        "噪音、採光與租約費用。"
    )


def generate_ai_summary(req: UserRequirements, ranked: list[dict[str, Any]]) -> tuple[str, str]:
    settings = get_settings()
    if not settings.openai_api_key:
        return build_rule_summary(ranked), "demo"

    try:
        from openai import OpenAI

        compact = [
            {
                "rank": index + 1,
                "title": item["property"].title,
                "score": item["total_score"],
                "monthly_cost": item["estimated_monthly_cost"],
                "strengths": item["strengths"],
                "tradeoffs": item["tradeoffs"],
            }
            for index, item in enumerate(ranked)
        ]
        client = OpenAI(api_key=settings.openai_api_key)
        response = client.responses.create(
            model=settings.openai_model,
            instructions=(
                "你是 RentWise 的 Comparison Agent。請使用繁體中文，根據多個"
                "專業 Agent 已完成的結構化結果，給出 120 字內、具體且不誇大的"
                "租屋決策摘要。需要提到首選、主要取捨與實地看房提醒。"
            ),
            input=json.dumps(
                {"requirements": req.model_dump(), "ranked_results": compact},
                ensure_ascii=False,
            ),
        )
        text = (response.output_text or "").strip()
        return (text or build_rule_summary(ranked)), "ai"
    except Exception:
        return build_rule_summary(ranked), "demo"
