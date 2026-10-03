import math
import re
import ssl
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Iterable
from urllib.parse import urlencode

import httpx
import certifi

from app.models.schemas import Property, PropertySourceLink, UserRequirements
from app.services.listing_text_service import (
    is_non_habitable_listing,
    parse_listing_costs,
    rental_subsidy_status,
)
from app.services.listing_detail_service import enrich_listing_detail_pages


RENT_591_LIST_URL = "https://rent.591.com.tw/list"
DEFAULT_IMAGE_URL = (
    "https://images.unsplash.com/photo-1522708323590-d24dbb6b0267"
    "?auto=format&fit=crop&w=1200&q=80"
)


class Rent591Error(RuntimeError):
    pass


REGIONS = {
    "台北市": 1,
    "臺北市": 1,
    "基隆市": 2,
    "新北市": 3,
    "新竹市": 4,
    "新竹縣": 5,
    "桃園市": 6,
    "苗栗縣": 7,
    "台中市": 8,
    "臺中市": 8,
    "彰化縣": 10,
    "南投縣": 11,
    "嘉義市": 12,
    "嘉義縣": 13,
    "雲林縣": 14,
    "台南市": 15,
    "臺南市": 15,
    "高雄市": 17,
    "屏東縣": 19,
    "宜蘭縣": 21,
    "台東縣": 22,
    "臺東縣": 22,
    "花蓮縣": 23,
    "澎湖縣": 24,
    "金門縣": 25,
    "連江縣": 26,
}

SECTIONS_BY_REGION = {
    1: {
        "中正區": 1, "大同區": 2, "中山區": 3, "松山區": 4,
        "大安區": 5, "萬華區": 6, "信義區": 7, "士林區": 8,
        "北投區": 9, "內湖區": 10, "南港區": 11, "文山區": 12,
    },
    3: {
        "板橋區": 26, "汐止區": 27, "深坑區": 28, "石碇區": 29,
        "瑞芳區": 30, "平溪區": 31, "雙溪區": 32, "貢寮區": 33,
        "新店區": 34, "坪林區": 35, "烏來區": 36, "永和區": 37,
        "中和區": 38, "土城區": 39, "三峽區": 40, "樹林區": 41,
        "鶯歌區": 42, "三重區": 43, "新莊區": 44, "泰山區": 45,
        "林口區": 46, "蘆洲區": 47, "五股區": 48, "八里區": 49,
        "淡水區": 50, "三芝區": 51, "石門區": 52,
    },
    4: {"香山區": 370, "東區": 371, "北區": 372},
    6: {
        "中壢區": 67, "平鎮區": 68, "龍潭區": 69, "楊梅區": 70,
        "新屋區": 71, "觀音區": 72, "桃園區": 73, "龜山區": 74,
        "八德區": 75, "大溪區": 76, "復興區": 77, "大園區": 78,
        "蘆竹區": 79,
    },
    8: {
        "中區": 98, "東區": 99, "南區": 100, "西區": 101,
        "北區": 102, "北屯區": 103, "西屯區": 104, "南屯區": 105,
        "太平區": 106, "大里區": 107, "霧峰區": 108, "烏日區": 109,
        "豐原區": 110, "后里區": 111, "石岡區": 112, "東勢區": 113,
        "和平區": 114, "新社區": 115, "潭子區": 116, "大雅區": 117,
        "神岡區": 118, "大肚區": 119, "沙鹿區": 120, "龍井區": 121,
        "梧棲區": 122, "清水區": 123, "大甲區": 124, "外埔區": 125,
        "大安區": 126,
    },
    12: {"西區": 373, "東區": 374},
    15: {
        "東區": 206, "南區": 207, "中西區": 208, "北區": 209,
        "安平區": 210, "安南區": 211, "永康區": 212, "歸仁區": 213,
        "新化區": 214, "左鎮區": 215, "楠西區": 217, "南化區": 218,
        "仁德區": 219, "關廟區": 220, "龍崎區": 221, "官田區": 222,
        "麻豆區": 223, "佳里區": 224, "西港區": 225, "七股區": 226,
        "將軍區": 227, "學甲區": 228, "北門區": 229, "新營區": 230,
    },
    17: {
        "新興區": 243, "前金區": 244, "苓雅區": 245, "鹽埕區": 246,
        "鼓山區": 247, "旗津區": 248, "前鎮區": 249, "三民區": 250,
        "楠梓區": 251, "小港區": 252, "左營區": 253, "仁武區": 254,
        "大社區": 255, "岡山區": 258, "路竹區": 259, "阿蓮區": 260,
        "田寮區": 261, "橋頭區": 263, "梓官區": 264, "彌陀區": 265,
        "永安區": 266, "湖內區": 267, "鳳山區": 268, "大寮區": 269,
        "林園區": 270, "鳥松區": 271, "大樹區": 272, "旗山區": 273,
        "美濃區": 274, "六龜區": 275, "內門區": 276, "杉林區": 277,
        "甲仙區": 278,
    },
}

DESTINATION_PRESETS = (
    (("政治大學", "政大"), {"region": 1, "school": 401}),
    (("台灣大學", "臺灣大學", "台大"), {"region": 1, "section": 5}),
    (("台灣師範大學", "臺灣師範大學", "師大"), {"region": 1, "section": 5}),
    (("台北科技大學", "臺北科技大學", "北科大"), {"region": 1, "section": 5}),
    (("台北醫學大學", "臺北醫學大學", "北醫"), {"region": 1, "section": 7}),
    (("世新大學", "世新"), {"region": 1, "section": 12}),
    (("台灣科技大學", "臺灣科技大學", "台科大"), {"region": 1, "section": 5}),
    (("輔仁大學", "輔大"), {"region": 3, "section": 44}),
    (("淡江大學", "淡大"), {"region": 3, "section": 50}),
    (("清華大學", "清大"), {"region": 4, "section": 371}),
    (("陽明交通大學", "陽明交大", "交大"), {"region": 4, "section": 371}),
    (("中央大學", "中大"), {"region": 6, "section": 67}),
    (("中興大學", "興大"), {"region": 8, "section": 100}),
    (("逢甲大學", "逢甲"), {"region": 8, "section": 104}),
    (("東海大學", "東海"), {"region": 8, "section": 104}),
    (("成功大學", "成大"), {"region": 15, "section": 206}),
    (("中山大學", "中山大"), {"region": 17, "section": 247}),
    (("高雄大學", "高大"), {"region": 17, "section": 251}),
    (("台北101", "臺北101", "台北市政府"), {"region": 1, "section": 7}),
    (("南港軟體園區", "南港軟體"), {"region": 1, "section": 11}),
    (("內湖科技園區", "內科"), {"region": 1, "section": 10}),
)


def resolve_591_location(destination: str) -> dict[str, int]:
    normalized = destination.strip()
    nearby_label = re.sub(
        r"(?:附近|周邊|一帶|旁邊)$",
        "",
        normalized,
    ).strip()
    for aliases, params in DESTINATION_PRESETS:
        if any(
            (
                normalized == alias
                or nearby_label == alias
                or (len(alias) >= 4 and alias in normalized)
            )
            for alias in aliases
        ):
            return params.copy()

    region = next(
        (region_id for name, region_id in REGIONS.items() if name in normalized),
        None,
    )
    matching_sections = [
        (region_id, section_id)
        for region_id, sections in SECTIONS_BY_REGION.items()
        for name, section_id in sections.items()
        if name in normalized and (region is None or region == region_id)
    ]
    if len(matching_sections) == 1:
        matched_region, section_id = matching_sections[0]
        return {"region": matched_region, "section": section_id}
    if len(matching_sections) > 1 and region is None:
        raise Rent591Error("行政區名稱可能位於多個縣市，請加上縣市名稱。")

    shorthand = normalized.removesuffix("區")
    shorthand_matches = [
        (region_id, section_id)
        for region_id, sections in SECTIONS_BY_REGION.items()
        for name, section_id in sections.items()
        if name.removesuffix("區") == shorthand
        and (region is None or region == region_id)
    ]
    if len(shorthand_matches) == 1:
        matched_region, section_id = shorthand_matches[0]
        return {"region": matched_region, "section": section_id}
    if len(shorthand_matches) > 1 and region is None:
        raise Rent591Error("行政區簡稱可能位於多個縣市，請加上縣市名稱。")

    district_like = re.search(r"[\u4e00-\u9fff]{1,4}(區|鄉|鎮)", normalized)
    if district_like and region is not None:
        raise Rent591Error(
            f"目前無法對應「{district_like.group(0)}」的 591 行政區代碼。"
        )
    if region is not None:
        return {"region": region}

    raise Rent591Error(
        "無法辨識目的地。請輸入縣市＋行政區，例如「台北市大安區」，"
        "或輸入支援的大學／地標名稱。"
    )


@dataclass
class HtmlNode:
    tag: str
    attrs: dict[str, str] = field(default_factory=dict)
    children: list["HtmlNode"] = field(default_factory=list)
    text_parts: list[str] = field(default_factory=list)

    @property
    def classes(self) -> set[str]:
        return set(self.attrs.get("class", "").split())

    def text(self) -> str:
        parts = list(self.text_parts)
        for child in self.children:
            parts.append(child.text())
        return " ".join(" ".join(parts).split())

    def descendants(self) -> Iterable["HtmlNode"]:
        for child in self.children:
            yield child
            yield from child.descendants()

    def first_with_class(self, class_name: str) -> "HtmlNode | None":
        return next(
            (node for node in self.descendants() if class_name in node.classes),
            None,
        )

    def all_with_class(self, class_name: str) -> list["HtmlNode"]:
        return [node for node in self.descendants() if class_name in node.classes]


class ListingParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.items: list[HtmlNode] = []
        self.stack: list[HtmlNode] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key: value or "" for key, value in attrs}
        classes = set(attributes.get("class", "").split())
        if not self.stack:
            if tag != "div" or "item" not in classes or not attributes.get("data-id"):
                return
            root = HtmlNode(tag=tag, attrs=attributes)
            self.items.append(root)
            self.stack.append(root)
            return

        node = HtmlNode(tag=tag, attrs=attributes)
        self.stack[-1].children.append(node)
        if tag not in {"img", "br", "meta", "link", "input", "source", "hr"}:
            self.stack.append(node)

    def handle_startendtag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        self.handle_starttag(tag, attrs)
        if self.stack and self.stack[-1].tag == tag:
            self.stack.pop()

    def handle_endtag(self, tag: str) -> None:
        if not self.stack:
            return
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                return

    def handle_data(self, data: str) -> None:
        if self.stack and data.strip():
            self.stack[-1].text_parts.append(data.strip())


def build_591_search_url(req: UserRequirements) -> str:
    params: dict[str, str | int] = resolve_591_location(req.destination)
    params["price"] = f"0_{req.budget}"
    filters = []
    if req.needs_elevator:
        filters.append("lift")
    if any("開伙" in preference for preference in req.preferences):
        filters.append("cook")
    if filters:
        params["other"] = ",".join(filters)
    return f"{RENT_591_LIST_URL}?{urlencode(params)}"


def _number(text: str, default: int = 0) -> int:
    match = re.search(r"[\d,]+", text)
    return int(match.group().replace(",", "")) if match else default


def _floor(text: str) -> int | None:
    match = re.search(r"(?<!B)(\d+)F/", text)
    if match:
        return int(match.group(1))
    if "1樓" in text or "一樓" in text:
        return 1
    return None


def _listing_to_property(node: HtmlNode, destination: str = "") -> Property | None:
    link = next(
        (
            item
            for item in node.descendants()
            if item.tag == "a"
            and "link" in item.classes
            and item.attrs.get("href", "").startswith("https://rent.591.com.tw/")
        ),
        None,
    )
    price_node = node.first_with_class("item-info-price")
    info_nodes = node.all_with_class("item-info-txt")
    if not link or not price_node or len(info_nodes) < 3:
        return None

    listing_id = node.attrs["data-id"]
    title = link.attrs.get("title") or link.text()
    source_url = link.attrs["href"]
    price = _number(price_node.text())
    if not title or not price:
        return None

    home_text = info_nodes[0].text()
    listing_text = node.text()
    if is_non_habitable_listing(title, home_text, listing_text):
        return None
    address = info_nodes[1].text()
    distance_text = info_nodes[2].text()
    distance_meters = _number(distance_text)
    destination_names = {
        destination.strip(),
        destination.strip().replace("政大", "政治大學"),
    }
    reference_match = any(
        name and name in distance_text for name in destination_names
    )
    commute_minutes = (
        max(1, math.ceil((distance_meters / 1000 * 1.25) / 4.5 * 60))
        if distance_meters and reference_match
        else None
    )

    tag_container = node.first_with_class("item-info-tag")
    tags = [
        item.text().strip()
        for item in (tag_container.descendants() if tag_container else [])
        if item.tag == "span" and item.text().strip()
    ]
    combined = " ".join([title, home_text, address, " ".join(tags), listing_text])

    image_urls = list(dict.fromkeys(
        item.attrs.get("data-src") or item.attrs.get("src")
        for item in node.descendants()
        if item.tag == "img"
        and (item.attrs.get("data-src") or item.attrs.get("src", "")).startswith("http")
    ))
    image_url = image_urls[0] if image_urls else DEFAULT_IMAGE_URL

    has_window = (
        True
        if any(word in combined for word in ("對外窗", "大外窗", "大窗", "採光"))
        else None
    )
    has_elevator = True if "有電梯" in combined or "電梯" in tags else None
    current_floor = _floor(home_text)
    noise_level = "low" if any(word in combined for word in ("安靜", "清幽", "寧靜")) else None

    nearby = []
    if any(word in combined.lower() for word in ("便利商店", "7-11", "711", "全家")):
        nearby.append("便利商店")
    if "近捷運" in combined or "捷運" in title:
        nearby.append("捷運站")
    if "近商圈" in combined:
        nearby.append("商圈")

    features = list(dict.fromkeys(tags + [part for part in home_text.split() if part]))[:8]
    risks = ["591 列表未完整揭露水電、管理費與屋況，簽約前需確認"]
    if has_window is None:
        risks.append("列表未確認是否有對外窗")
    if has_elevator is None:
        risks.append("列表未確認是否有電梯")

    costs = parse_listing_costs(listing_text)

    return Property(
        id=f"591-{listing_id}",
        title=title,
        address=address,
        rent=price,
        management_fee=costs.management_fee,
        water_fee=costs.water_fee,
        electricity_rate=costs.electricity_rate,
        estimated_kwh=costs.estimated_kwh,
        management_fee_disclosed=costs.management_fee_disclosed,
        water_fee_disclosed=costs.water_fee_disclosed,
        electricity_rate_disclosed=costs.electricity_rate_disclosed,
        electricity_usage_disclosed=costs.electricity_usage_disclosed,
        commute_minutes=commute_minutes,
        distance_reference=distance_text,
        commute_method="591 距離步行推估" if commute_minutes else "",
        route_distance_km=(
            round(distance_meters / 1000 * 1.25, 1)
            if commute_minutes
            else None
        ),
        has_window=has_window,
        window_type="疑似有對外窗" if has_window else "591 列表未揭露",
        has_elevator=has_elevator,
        floor=current_floor,
        noise_level=noise_level,
        nearby=nearby,
        rental_subsidy_eligible=rental_subsidy_status(combined),
        listing_area_ping=(
            float(area_match.group(1))
            if (area_match := re.search(r"(\d+(?:\.\d+)?)\s*坪", combined))
            else None
        ),
        features=features,
        risks=risks,
        description=f"{home_text}；{distance_text}",
        listing_text=listing_text[:12000],
        image_url=image_url,
        image_urls=image_urls,
        source_name="591租屋",
        source_url=source_url,
        source_links=[
            PropertySourceLink(name="591租屋", url=source_url)
        ],
        data_notes=[
            (
                "優先使用地址定位與道路路網計算；無法定位時，若 591 距離"
                "參考點與目的地相符，改用地理距離步行推估"
            ),
            (
                "費用依 591 刊登文字逐項辨識；已標示含水費時水費為 0 元，"
                "其餘未揭露項目才交由 Cost Agent 補估"
            ),
        ],
    )


def parse_591_listings(
    html: str, limit: int = 12, destination: str = ""
) -> list[Property]:
    parser = ListingParser()
    parser.feed(html)
    properties = []
    seen = set()
    for node in parser.items:
        property_ = _listing_to_property(node, destination=destination)
        if not property_ or property_.id in seen:
            continue
        seen.add(property_.id)
        properties.append(property_)
        if len(properties) >= limit:
            break
    return properties


def fetch_591_properties(req: UserRequirements, limit: int = 12) -> list[Property]:
    url = build_591_search_url(req)
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    if hasattr(ssl, "VERIFY_X509_STRICT"):
        # 591's current certificate chain omits an extension required by
        # Python 3.14 strict mode. Keep CA and hostname verification enabled.
        ssl_context.verify_flags &= ~ssl.VERIFY_X509_STRICT
    try:
        response = httpx.get(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 Chrome/126 Safari/537.36"
                ),
                "Accept-Language": "zh-TW,zh;q=0.9",
            },
            follow_redirects=True,
            timeout=20,
            verify=ssl_context,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise Rent591Error("目前無法連線到 591，請稍後再試。") from exc

    properties = parse_591_listings(
        response.text,
        limit=limit,
        destination=req.destination,
    )
    if not properties:
        raise Rent591Error("591 沒有回傳可分析的房源，可能暫時限制了自動存取。")
    return enrich_listing_detail_pages(properties, limit=limit)
