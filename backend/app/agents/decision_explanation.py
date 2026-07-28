import json
from typing import Any

from app.config import get_settings
from app.models.schemas import UserRequirements


def build_rule_summary(ranked: list[dict[str, Any]]) -> str:
    best = ranked[0]
    property_ = best["property"]
    qualified = bool(
        best["assessments"]["suitability"].metrics.get("qualified", True)
    )
    if not qualified:
        return (
            "目前沒有房源符合全部必要條件。參考分最高的是"
            f"「{property_.title}」，但明確衝突為"
            f"{best['assessments']['suitability'].metrics.get('disqualifying_conflicts', '必要條件')}；"
            "建議調整條件或擴大搜尋範圍，而不是直接簽約。"
        )
    return (
        f"綜合多個 Agent 的分析，首選為「{property_.title}」，"
        f"適配分數 {best['total_score']:.1f} 分，預估每月支出 "
        f"{best['estimated_monthly_cost']:,} 元。此排名同時考量通勤、"
        "真實生活成本、房況硬體與個人生活偏好；建議簽約前仍實地確認"
        "安靜程度、採光與租約費用。"
    )


def generate_decision_explanation(
    req: UserRequirements,
    ranked: list[dict[str, Any]],
    destination_context: str = "",
) -> tuple[str, str]:
    settings = get_settings()
    if not settings.openai_api_key:
        return build_rule_summary(ranked), "rules"

    try:
        from openai import OpenAI

        compact = [
            {
                "rank": index + 1,
                "title": item["property"].title,
                "score": item["total_score"],
                "monthly_cost": item["estimated_monthly_cost"],
                "address": item["property"].address,
                "commute_minutes": item["property"].commute_minutes,
                "qualified": item["assessments"]["suitability"].metrics.get(
                    "qualified",
                    True,
                ),
                "disqualifying_conflicts": item["assessments"][
                    "suitability"
                ].metrics.get("disqualifying_conflicts", ""),
                "strengths": item["strengths"],
                "tradeoffs": item["tradeoffs"],
                "agent_summaries": {
                    name: assessment.summary
                    for name, assessment in item["assessments"].items()
                },
            }
            for index, item in enumerate(ranked)
        ]
        client = OpenAI(api_key=settings.openai_api_key)
        response = client.responses.create(
            model=settings.openai_model,
            instructions=(
                "你是 RentWise 的 Decision Explanation Agent。請使用繁體中文，"
                "根據多個"
                "專業 Agent 已完成的結構化結果，給出 120 字內、具體且不誇大的"
                "租屋決策摘要。需要理解目的地的完整地理脈絡，提到首選、主要"
                "取捨與實地看房提醒；AI 估算與圖片判讀必須保留不確定性。"
            ),
            input=json.dumps(
                {
                    "requirements": req.model_dump(),
                    "destination_context": destination_context or req.destination,
                    "ranked_results": compact,
                },
                ensure_ascii=False,
            ),
        )
        text = (response.output_text or "").strip()
        return (text or build_rule_summary(ranked)), "ai"
    except Exception:
        return build_rule_summary(ranked), "rules"
