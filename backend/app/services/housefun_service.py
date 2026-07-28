import base64
import json
import re
from html.parser import HTMLParser
from typing import Any

import httpx

from app.models.schemas import Property, PropertySourceLink, UserRequirements
from app.services.listing_text_service import (
    is_non_habitable_listing,
    parse_listing_costs,
    rental_subsidy_status,
)
from app.services.listing_detail_service import enrich_listing_detail_pages
from app.services.map_service import _ssl_context
from app.services.rent591_service import DEFAULT_IMAGE_URL
from app.services.source_planning_service import SourceSearchPlan


HOUSEFUN_SEARCH_URL = "https://rent.housefun.com.tw/ashx/search/search.ashx"
HOUSEFUN_BASE_URL = "https://rent.housefun.com.tw"


class HousefunError(RuntimeError):
    pass


class Node:
    def __init__(self, tag: str, attrs: dict[str, str]) -> None:
        self.tag = tag
        self.attrs = attrs
        self.children: list["Node"] = []
        self.text_parts: list[str] = []

    @property
    def classes(self) -> set[str]:
        return set(self.attrs.get("class", "").split())

    def text(self) -> str:
        parts = list(self.text_parts)
        for child in self.children:
            parts.append(child.text())
        return " ".join(" ".join(parts).split())

    def descendants(self):
        for child in self.children:
            yield child
            yield from child.descendants()

    def first_with_class(self, class_name: str) -> "Node | None":
        return next(
            (
                node
                for node in self.descendants()
                if class_name in node.classes
            ),
            None,
        )


class HousefunListParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.items: list[Node] = []
        self.stack: list[Node] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        attributes = {key: value or "" for key, value in attrs}
        classes = set(attributes.get("class", "").split())
        if not self.stack:
            if tag != "article" or "DataList" not in classes:
                return
            root = Node(tag, attributes)
            self.items.append(root)
            self.stack.append(root)
            return

        node = Node(tag, attributes)
        self.stack[-1].children.append(node)
        if tag not in {"img", "br", "meta", "link", "input", "hr"}:
            self.stack.append(node)

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


def _b64(value: str) -> str:
    return base64.b64encode(value.encode("utf-8")).decode("ascii")


def _encode_strings(value: Any) -> Any:
    if isinstance(value, str):
        return _b64(value)
    if isinstance(value, dict):
        return {key: _encode_strings(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_encode_strings(item) for item in value]
    return value


def _decode_string(value: str) -> str:
    try:
        decoded = base64.b64decode(value, validate=True)
        return decoded.decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return value


def _decode_strings(value: Any) -> Any:
    if isinstance(value, str):
        return _decode_string(value)
    if isinstance(value, dict):
        return {key: _decode_strings(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_decode_strings(item) for item in value]
    return value


def _number(text: str) -> int:
    match = re.search(r"[\d,]+", text)
    return int(match.group().replace(",", "")) if match else 0


def _float(text: str) -> float | None:
    match = re.search(r"\d+(?:\.\d+)?", text)
    return float(match.group()) if match else None


def parse_housefun_listings(html: str, limit: int = 8) -> list[Property]:
    parser = HousefunListParser()
    parser.feed(html)
    properties = []
    for item in parser.items:
        title_node = item.first_with_class("title")
        address_node = item.first_with_class("addr")
        if not title_node or not address_node:
            continue
        detail_link = next(
            (
                node
                for node in title_node.descendants()
                if node.tag == "a"
                and re.match(r"^/rent/house/\d+/?$", node.attrs.get("href", ""))
            ),
            None,
        )
        if not detail_link:
            continue
        listing_match = re.search(r"/rent/house/(\d+)", detail_link.attrs["href"])
        if not listing_match:
            continue
        listing_id = listing_match.group(1)
        title = detail_link.attrs.get("title") or detail_link.text()
        address = address_node.text()
        full_text = item.text()
        if is_non_habitable_listing(title, "", full_text):
            continue
        rent_match = re.search(r"租金[：:]?\s*([\d,]+)", full_text)
        rent = _number(rent_match.group(1)) if rent_match else 0
        if not title or not address or not rent:
            continue
        costs = parse_listing_costs(full_text)

        area_match = re.search(r"坪數[：:]?\s*([\d.]+)", full_text)
        area = _float(area_match.group(1)) if area_match else None
        floor_match = re.search(r"樓層[：:]?\s*(\d+)\s*/", full_text)
        floor = int(floor_match.group(1)) if floor_match else None
        room_match = re.search(r"(\d+)房(?:\([^)]*\))?(\d+)廳(\d+)衛", full_text)

        image_urls = list(dict.fromkeys(
            node.attrs["src"]
            for node in item.descendants()
            if node.tag == "img" and node.attrs.get("src", "").startswith("http")
        ))
        image_url = image_urls[0] if image_urls else DEFAULT_IMAGE_URL

        latitude = longitude = None
        map_link = next(
            (
                node.attrs.get("href", "")
                for node in item.descendants()
                if "LatLng=" in node.attrs.get("href", "")
            ),
            "",
        )
        coordinate_match = re.search(
            r"LatLng=(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)",
            map_link,
        )
        if coordinate_match:
            latitude = float(coordinate_match.group(1))
            longitude = float(coordinate_match.group(2))

        features = []
        if room_match:
            features.append(
                f"{room_match.group(1)}房"
                f"{room_match.group(2)}廳{room_match.group(3)}衛"
            )
        if area is not None:
            features.append(f"{area:g}坪")
        if "電梯" in full_text:
            features.append("電梯")

        source_url = f"{HOUSEFUN_BASE_URL}/rent/house/{listing_id}/"
        properties.append(
            Property(
                id=f"housefun-{listing_id}",
                title=title,
                address=address,
                rent=rent,
                management_fee=costs.management_fee,
                water_fee=costs.water_fee,
                electricity_rate=costs.electricity_rate,
                estimated_kwh=costs.estimated_kwh,
                management_fee_disclosed=costs.management_fee_disclosed,
                water_fee_disclosed=costs.water_fee_disclosed,
                electricity_rate_disclosed=costs.electricity_rate_disclosed,
                electricity_usage_disclosed=costs.electricity_usage_disclosed,
                commute_minutes=None,
                has_window=None,
                window_type="好房網列表未揭露",
                has_elevator=True if "電梯" in full_text else None,
                floor=floor,
                noise_level=None,
                nearby=[],
                rental_subsidy_eligible=rental_subsidy_status(full_text),
                listing_area_ping=area,
                features=features,
                risks=["列表未完整揭露費用與設備，簽約前需確認"],
                description=full_text[:500],
                listing_text=full_text[:12000],
                image_url=image_url,
                image_urls=image_urls,
                source_name="好房網快租",
                source_url=source_url,
                source_links=[
                    PropertySourceLink(name="好房網快租", url=source_url)
                ],
                latitude=latitude,
                longitude=longitude,
                data_notes=[
                    "房源來自好房網公開租屋搜尋結果",
                    (
                        "費用依刊登文字逐項辨識；已標示包含的費用不會重複估算"
                    ),
                ],
            )
        )
        if len(properties) >= limit:
            break
    return properties


def _search(keyword: str, budget: int) -> list[Property]:
    request_data = {
        "DataUnit": "1",
        "KeyWord": keyword,
        "PriceH": str(budget),
        "PMPage": "1",
        "OrderBy": "ByUpdate",
        "OrderType": "Desc",
    }
    package = {
        "Method": _b64("INQUIRE"),
        "Data": _encode_strings(request_data),
    }
    response = httpx.post(
        HOUSEFUN_SEARCH_URL,
        data={"RequestPackage": json.dumps(package, ensure_ascii=False)},
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 Chrome/126 Safari/537.36"
            ),
            "Referer": f"{HOUSEFUN_BASE_URL}/",
        },
        timeout=20,
        verify=_ssl_context(),
    )
    response.raise_for_status()
    body = _decode_strings(response.json())
    if body.get("Status") != "1":
        raise HousefunError(body.get("StatusMessage", "好房網搜尋失敗"))
    html = body.get("Data", {}).get("SearchContent", "")
    return parse_housefun_listings(html)


def fetch_housefun_properties(
    req: UserRequirements,
    plan: SourceSearchPlan,
    limit: int = 8,
) -> list[Property]:
    properties = []
    seen = set()
    for keyword in plan.keywords:
        try:
            listings = _search(keyword, req.budget)
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise HousefunError("目前無法連線到好房網，請稍後再試。") from exc
        for property_ in listings:
            if property_.id in seen:
                continue
            seen.add(property_.id)
            properties.append(property_)
            if len(properties) >= limit:
                return enrich_listing_detail_pages(properties, limit=limit)
    return enrich_listing_detail_pages(properties, limit=limit)
