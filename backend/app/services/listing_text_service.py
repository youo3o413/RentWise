import re
from dataclasses import dataclass


RENTAL_SUBSIDY_NEGATIVE_PATTERNS = (
    r"不可(?:申請)?租補",
    r"不能(?:申請)?租補",
    r"不配合(?:申請)?(?:租補|租金補貼|租屋補助)",
    r"謝絕(?:租補|租金補貼|租屋補助)",
    r"不可申請租金補貼",
    r"無法申請租金補貼",
    r"不接受租屋補助",
)
RENTAL_SUBSIDY_POSITIVE_PATTERNS = (
    r"可(?:申請)?租補",
    r"可以(?:申請)?租補",
    r"配合(?:申請)?租補",
    r"可申請租金補貼",
    r"可申請租屋補助",
    r"租補友善",
    r"租屋補助友善",
    r"可報稅",
    r"可入籍",
    r"(?:300億|三百億).{0,8}租金補貼",
    r"中央擴大租金補貼",
    r"租金補貼",
    r"租屋補助",
)
RENTAL_SUBSIDY_UNCERTAIN_PATTERNS = (
    r"租補(?:另議|面議|需確認|請詢問|洽談)",
    r"租金補貼(?:另議|面議|需確認|請詢問|洽談)",
)

DWELLING_PATTERNS = (
    r"套房",
    r"雅房",
    r"整層",
    r"住家",
    r"住宅",
    r"公寓",
    r"華廈",
    r"透天",
    r"\d+房(?:\d+廳)?",
)
PARKING_ONLY_PATTERNS = (
    r"(?:汽車|機車|平面|機械|坡道)?車位(?:出租|招租|月租)",
    r"(?:出租|月租)(?:汽車|機車|平面|機械|坡道)?車位",
    r"停車位(?:出租|招租|月租)",
    r"(?:坡道平面|坡道機械|升降機械)車位",
)
NON_HABITABLE_PATTERNS = (
    r"(?:置物|儲物)(?:空間|室|間)(?:出租|招租|月租)?",
    r"(?:出租|招租|月租)(?:置物|儲物)(?:空間|室|間)",
    r"(?:迷你倉|個人倉|倉儲空間|倉庫)(?:出租|招租|月租)?",
    r"(?:出租|招租|月租)(?:迷你倉|個人倉|倉儲空間|倉庫)",
    r"僅供(?:置物|儲物|倉儲|堆放)",
    r"(?:禁止|不可|不得)(?:居住|過夜|住宿)",
)


@dataclass(frozen=True)
class ListingCostInfo:
    management_fee: int = 0
    water_fee: int = 0
    electricity_rate: float = 5.0
    estimated_kwh: int = 100
    management_fee_disclosed: bool = False
    water_fee_disclosed: bool = False
    electricity_rate_disclosed: bool = False
    electricity_usage_disclosed: bool = False


def rental_subsidy_status(text: str) -> bool | None:
    compact = re.sub(r"\s+", "", text or "")
    if any(re.search(pattern, compact) for pattern in RENTAL_SUBSIDY_NEGATIVE_PATTERNS):
        return False
    if any(re.search(pattern, compact) for pattern in RENTAL_SUBSIDY_UNCERTAIN_PATTERNS):
        return None
    if any(re.search(pattern, compact) for pattern in RENTAL_SUBSIDY_POSITIVE_PATTERNS):
        return True
    return None


def is_parking_only_listing(title: str, category: str = "", text: str = "") -> bool:
    compact_title = re.sub(r"\s+", "", title or "")
    compact_category = re.sub(r"\s+", "", category or "")
    compact_text = re.sub(r"\s+", "", text or "")
    combined = f"{compact_title}{compact_category}{compact_text}"
    has_dwelling = any(
        re.search(pattern, f"{compact_title}{compact_category}")
        for pattern in DWELLING_PATTERNS
    )
    category_is_parking = bool(
        re.search(r"(?:^|出租)車位|停車位|汽車位|機車位", compact_category)
    )
    title_is_parking = any(
        re.search(pattern, compact_title)
        for pattern in PARKING_ONLY_PATTERNS
    )
    text_is_clearly_parking = (
        any(re.search(pattern, combined) for pattern in PARKING_ONLY_PATTERNS)
        and not any(re.search(pattern, combined) for pattern in DWELLING_PATTERNS)
    )
    return not has_dwelling and (
        category_is_parking or title_is_parking or text_is_clearly_parking
    )


def is_non_habitable_listing(
    title: str,
    category: str = "",
    text: str = "",
) -> bool:
    if is_parking_only_listing(title, category, text):
        return True
    compact_title = re.sub(r"\s+", "", title or "")
    compact_category = re.sub(r"\s+", "", category or "")
    compact_text = re.sub(r"\s+", "", text or "")
    heading = f"{compact_title}{compact_category}"
    has_dwelling_heading = any(
        re.search(pattern, heading)
        for pattern in DWELLING_PATTERNS
    )
    if any(re.search(pattern, heading) for pattern in NON_HABITABLE_PATTERNS):
        return not has_dwelling_heading
    return (
        not has_dwelling_heading
        and any(re.search(pattern, compact_text) for pattern in NON_HABITABLE_PATTERNS)
        and not any(re.search(pattern, compact_text) for pattern in DWELLING_PATTERNS)
    )


def _monthly_amount(compact: str, label: str) -> int | None:
    patterns = (
        rf"{label}(?:每月|月繳|[:：])?(?:新台幣)?([\d,]+)元",
        rf"每月{label}(?:[:：])?(?:新台幣)?([\d,]+)元",
    )
    for pattern in patterns:
        if match := re.search(pattern, compact):
            return int(match.group(1).replace(",", ""))
    return None


def parse_listing_costs(text: str) -> ListingCostInfo:
    compact = re.sub(r"\s+", "", text or "")

    management_included = bool(
        re.search(r"(?:租金)?(?:已?含|包含)管理費|管理費(?:已?含|包含)(?:租金)?", compact)
    )
    management_amount = _monthly_amount(compact, "管理費")
    management_disclosed = management_included or management_amount is not None

    water_included = bool(
        re.search(
            r"(?:租金)?(?:已?含|包含)水(?:費)?|水費(?:已?含|包含)(?:租金)?|水費全包",
            compact,
        )
    )
    water_amount = _monthly_amount(compact, "水費")
    water_disclosed = water_included or water_amount is not None

    electricity_included = bool(
        re.search(
            r"(?:租金)?(?:已?含|包含)(?:水)?電費|電費(?:已?含|包含)(?:租金)?|"
            r"水電全包|電費全包",
            compact,
        )
    )
    electricity_rate = None
    rate_patterns = (
        r"(?:電費|電價)(?:每度|一度|[:：])?(?:新台幣)?(\d+(?:\.\d+)?)元?(?:/度)?",
        r"(?:每度|一度)(?:電)?(?:新台幣)?(\d+(?:\.\d+)?)元",
    )
    for pattern in rate_patterns:
        if match := re.search(pattern, compact):
            candidate = float(match.group(1))
            if 0 <= candidate <= 20:
                electricity_rate = candidate
                break

    return ListingCostInfo(
        management_fee=0 if management_included else management_amount or 0,
        water_fee=0 if water_included else water_amount or 0,
        electricity_rate=(
            0 if electricity_included else electricity_rate or 5.0
        ),
        estimated_kwh=0 if electricity_included else 100,
        management_fee_disclosed=management_disclosed,
        water_fee_disclosed=water_disclosed,
        electricity_rate_disclosed=(
            electricity_included or electricity_rate is not None
        ),
        electricity_usage_disclosed=electricity_included,
    )
