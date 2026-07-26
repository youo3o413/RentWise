from typing import Any, Literal

from openai import OpenAI, OpenAIError, RateLimitError
from pydantic import BaseModel, Field

from app.config import get_settings
from app.models.schemas import (
    CommunityEvidence,
    CommunityFinding,
    EvidenceSource,
    Property,
    UserRequirements,
)


PUBLIC_COMMUNITY_DOMAINS = [
    "ptt.cc",
    "dcard.tw",
    "mobile01.com",
    "reddit.com",
]
COMMUNITY_PREFERENCE_TERMS = (
    "養貓",
    "養狗",
    "寵物",
    "隔音",
    "治安",
    "夜間安全",
    "社區評價",
    "鄰居",
    "風評",
)


class CommunitySearchFinding(BaseModel):
    topic: str
    sentiment: Literal["positive", "mixed", "negative", "no_evidence"]
    scope: Literal["exact_property", "same_building", "nearby_area", "general_area"]
    summary: str


class CommunitySearchOutput(BaseModel):
    overview: str = Field(max_length=240)
    findings: list[CommunitySearchFinding]


def community_preferences(req: UserRequirements) -> list[str]:
    return [
        preference
        for preference in req.preferences
        if any(term in preference for term in COMMUNITY_PREFERENCE_TERMS)
    ]


def _citation_sources(response: Any) -> list[EvidenceSource]:
    sources = []
    seen_urls = set()
    for item in getattr(response, "output", []):
        for content in getattr(item, "content", []):
            for annotation in getattr(content, "annotations", []):
                url = getattr(annotation, "url", None)
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                sources.append(
                    EvidenceSource(
                        title=getattr(annotation, "title", None)
                        or "公開社群來源",
                        url=url,
                    )
                )
    return sources[:4]


def _search_property(
    client: OpenAI,
    model: str,
    property_: Property,
    preferences: list[str],
) -> CommunityEvidence:
    prompt = f"""
你是 RentWise 的 Community Evidence Agent。請搜尋公開社群頁面，查找與下列房源
或其所在街區有關的租屋經驗，只回答繁體中文：

房源：{property_.title}
地址：{property_.address}
想確認：{"、".join(preferences)}

要求：
- 排除 Facebook、登入限定內容、房仲廣告與無來源推測。
- 優先找可辨認為相同社區、街道或生活圈的使用者經驗。
- 若找不到相同房源證據，明確寫「未找到該房源的直接社群證據」。
- 「附近寵物友善」不能說成「房東允許養寵物」；租約權限一律提醒向房東確認。
- 隔音、治安與鄰居評價屬主觀經驗，不得當成確定事實。
- 以 100 字內摘要，必須保留不確定性。
""".strip()
    response = client.responses.parse(
        model=model,
        tools=[
            {
                "type": "web_search",
                "filters": {
                    "allowed_domains": PUBLIC_COMMUNITY_DOMAINS,
                },
                "search_context_size": "low",
            }
        ],
        input=(
            prompt
            + "\n請為每個想確認的主題回傳一筆結構化 finding。"
            "sentiment 只能是 positive、mixed、negative、no_evidence；"
            "scope 只能是 exact_property、same_building、nearby_area、general_area。"
        ),
        text_format=CommunitySearchOutput,
        max_output_tokens=700,
        timeout=25,
    )
    sources = _citation_sources(response)
    parsed = response.output_parsed
    findings = [
        CommunityFinding(
            topic=item.topic,
            sentiment=(
                item.sentiment
                if item.sentiment
                in {"positive", "mixed", "negative", "no_evidence"}
                else "no_evidence"
            ),
            scope=(
                item.scope
                if item.scope
                in {"exact_property", "same_building", "nearby_area", "general_area"}
                else "general_area"
            ),
            summary=item.summary,
        )
        for item in (parsed.findings if parsed else [])
    ]
    summary = (parsed.overview if parsed else "").strip()
    return CommunityEvidence(
        status="found" if sources and any(
            item.sentiment != "no_evidence" for item in findings
        ) else "not_found",
        summary=summary or "未找到可引用的公開社群意見。",
        confidence=(
            "medium"
            if len(sources) >= 2
            and any(item.scope in {"exact_property", "same_building"} for item in findings)
            else "low"
        ),
        searched_preferences=preferences,
        findings=findings,
        sources=sources,
    )


def collect_community_evidence(
    req: UserRequirements,
    properties: list[Property],
) -> tuple[dict[str, CommunityEvidence], str]:
    preferences = community_preferences(req)
    if not req.use_community_evidence:
        return {}, "未啟用公開社群查證"
    if not preferences:
        return {}, "需求中沒有需要社群查證的主觀條件"

    settings = get_settings()
    if not settings.openai_api_key:
        return {}, "未設定 OpenAI API Key，略過公開社群查證"

    client = OpenAI(api_key=settings.openai_api_key)
    evidence = {}
    try:
        for property_ in properties[:3]:
            evidence[property_.id] = _search_property(
                client,
                settings.openai_model,
                property_,
                preferences,
            )
    except RateLimitError as exc:
        if getattr(exc, "code", None) == "insufficient_quota":
            return {}, "OpenAI API 額度不足，略過公開社群查證"
        return evidence, "OpenAI 搜尋頻率受限，僅保留部分社群結果"
    except (OpenAIError, ValueError, TypeError):
        return evidence, "公開社群搜尋暫時無法使用"
    return evidence, f"已查證前 {len(evidence)} 筆候選房源的公開社群意見"
