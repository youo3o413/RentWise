import re
import ssl
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser

import certifi
import httpx

from app.models.schemas import Property
from app.services.listing_text_service import (
    parse_listing_costs,
    rental_subsidy_status,
)


class VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.image_urls: list[str] = []
        self.ignored_depth = 0

    def handle_starttag(self, tag, attrs) -> None:
        attributes = dict(attrs)
        if tag in {"img", "source"}:
            for key in ("data-src", "data-original", "src"):
                url = attributes.get(key, "")
                lower_url = url.lower()
                if (
                    url.startswith("http")
                    and not any(
                        term in lower_url
                        for term in ("logo", "icon", "avatar", "sprite", "qrcode")
                    )
                    and url not in self.image_urls
                ):
                    self.image_urls.append(url)
                    break
        if tag in {"script", "style", "noscript", "svg"}:
            self.ignored_depth += 1

    def handle_endtag(self, tag) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self.ignored_depth:
            self.ignored_depth -= 1

    def handle_data(self, data) -> None:
        if not self.ignored_depth and data.strip():
            self.parts.append(data.strip())


def extract_visible_listing_text(html: str, limit: int = 12000) -> str:
    parser = VisibleTextParser()
    parser.feed(html)
    return " ".join(" ".join(parser.parts).split())[:limit]


def extract_listing_images(html: str, limit: int = 8) -> list[str]:
    parser = VisibleTextParser()
    parser.feed(html)
    return parser.image_urls[:limit]


def _ssl_context() -> ssl.SSLContext:
    context = ssl.create_default_context(cafile=certifi.where())
    if hasattr(ssl, "VERIFY_X509_STRICT"):
        context.verify_flags &= ~ssl.VERIFY_X509_STRICT
    return context


def _fetch_detail(property_: Property) -> Property:
    if not property_.source_url.startswith("http"):
        return property_
    try:
        response = httpx.get(
            property_.source_url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 Chrome/126 Safari/537.36"
                ),
                "Accept-Language": "zh-TW,zh;q=0.9",
            },
            follow_redirects=True,
            timeout=12,
            verify=_ssl_context(),
        )
        response.raise_for_status()
        detail_text = extract_visible_listing_text(response.text)
        detail_images = extract_listing_images(response.text)
    except (httpx.HTTPError, ValueError):
        return property_
    if len(detail_text) < 80:
        return property_
    combined = " ".join(
        dict.fromkeys(
            part for part in (property_.listing_text, detail_text) if part
        )
    )
    image_urls = list(
        dict.fromkeys(
            [
                property_.image_url,
                *property_.image_urls,
                *detail_images,
            ]
        )
    )[:8]
    costs = parse_listing_costs(detail_text)
    cost_updates = {}
    for value_field, disclosed_field in (
        ("management_fee", "management_fee_disclosed"),
        ("water_fee", "water_fee_disclosed"),
        ("electricity_rate", "electricity_rate_disclosed"),
        ("estimated_kwh", "electricity_usage_disclosed"),
    ):
        if getattr(costs, disclosed_field):
            cost_updates[value_field] = getattr(costs, value_field)
            cost_updates[disclosed_field] = True
    subsidy = rental_subsidy_status(detail_text)
    return property_.model_copy(
        update={
            **cost_updates,
            "rental_subsidy_eligible": (
                subsidy
                if subsidy is not None
                else property_.rental_subsidy_eligible
            ),
            "listing_text": re.sub(r"\s+", " ", combined)[:12000],
            "listing_text_source": "detail_page",
            "image_url": image_urls[0] if image_urls else property_.image_url,
            "image_urls": image_urls,
            "data_notes": list(
                dict.fromkeys(
                    property_.data_notes + ["已讀取原始刊登詳情頁供需求語意判讀"]
                )
            ),
        }
    )


def enrich_listing_detail_pages(
    properties: list[Property],
    limit: int = 8,
) -> list[Property]:
    targets = properties[:limit]
    with ThreadPoolExecutor(max_workers=min(4, len(targets) or 1)) as executor:
        enriched = list(executor.map(_fetch_detail, targets))
    return enriched + properties[limit:]
