import json
import re
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path

from app.models.schemas import Property, PropertySourceLink, UserRequirements
from app.services.housefun_service import (
    HousefunError,
    fetch_housefun_properties,
)
from app.services.listing_text_service import is_parking_only_listing
from app.services.rent591_service import Rent591Error, fetch_591_properties
from app.services.source_planning_service import (
    SourceSearchPlan,
    build_source_search_plan,
)


DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "properties.json"


@lru_cache
def load_properties() -> list[Property]:
    with DATA_PATH.open("r", encoding="utf-8") as file:
        data = json.load(file)
    return [Property.model_validate(item) for item in data]


def _dedupe_key(property_: Property) -> tuple[int, str]:
    normalized_address = re.sub(
        r"台灣|臺灣|台北市|臺北市|新北市|桃園市|台中市|臺中市|"
        r"台南市|臺南市|高雄市|新竹市|新竹縣|[\s\-]",
        "",
        property_.address,
    )
    street_match = re.search(
        r"[\u4e00-\u9fff\d]+(?:路|街|大道)"
        r"(?:[一二三四五六七八九十\d]+段)?(?:\d+巷)?",
        normalized_address,
    )
    location_key = (
        street_match.group(0)
        if street_match
        else normalized_address[:18]
        or re.sub(r"\s+", "", property_.title)[:18]
    )
    return property_.rent, location_key


def _merge_duplicate(primary: Property, duplicate: Property) -> Property:
    links = list(primary.source_links)
    if not links and primary.source_url:
        links.append(
            PropertySourceLink(
                name=primary.source_name,
                url=primary.source_url,
            )
        )
    duplicate_links = duplicate.source_links or (
        [
            PropertySourceLink(
                name=duplicate.source_name,
                url=duplicate.source_url,
            )
        ]
        if duplicate.source_url
        else []
    )
    existing_urls = {link.url for link in links}
    links.extend(
        link for link in duplicate_links if link.url not in existing_urls
    )
    source_names = "／".join(dict.fromkeys(link.name for link in links))

    cost_updates = {}
    for value_field, disclosed_field in (
        ("management_fee", "management_fee_disclosed"),
        ("water_fee", "water_fee_disclosed"),
        ("electricity_rate", "electricity_rate_disclosed"),
        ("estimated_kwh", "electricity_usage_disclosed"),
    ):
        if (
            not getattr(primary, disclosed_field)
            and getattr(duplicate, disclosed_field)
        ):
            cost_updates[value_field] = getattr(duplicate, value_field)
            cost_updates[disclosed_field] = True

    subsidy_values = {
        value
        for value in (
            primary.rental_subsidy_eligible,
            duplicate.rental_subsidy_eligible,
        )
        if value is not None
    }
    rental_subsidy_eligible = (
        False
        if False in subsidy_values
        else True
        if True in subsidy_values
        else None
    )
    return primary.model_copy(
        update={
            **cost_updates,
            "rental_subsidy_eligible": rental_subsidy_eligible,
            "source_name": source_names or primary.source_name,
            "source_links": links,
            "data_notes": list(
                dict.fromkeys(
                    primary.data_notes
                    + duplicate.data_notes
                    + ["此房源可能同時刊登於多個平台"]
                )
            ),
        }
    )


def merge_and_dedupe_properties(
    source_groups: list[list[Property]],
    limit: int = 12,
) -> list[Property]:
    merged: list[Property] = []
    index_by_key: dict[tuple[int, str], int] = {}
    for group in source_groups:
        for property_ in group:
            if is_parking_only_listing(
                property_.title,
                "",
                property_.description,
            ):
                continue
            key = _dedupe_key(property_)
            if key in index_by_key:
                index = index_by_key[key]
                merged[index] = _merge_duplicate(merged[index], property_)
                continue
            index_by_key[key] = len(merged)
            merged.append(property_)
    return merged[:limit]


def _load_multi_source(
    req: UserRequirements,
    plan: SourceSearchPlan,
) -> list[Property]:
    planned_req = req.model_copy(
        update={"destination": plan.resolved_address or req.destination}
    )
    loaders = {
        "591租屋": lambda: fetch_591_properties(planned_req, limit=8),
        "好房網快租": lambda: fetch_housefun_properties(req, plan, limit=8),
    }
    results: dict[str, list[Property]] = {}
    errors = []
    with ThreadPoolExecutor(max_workers=len(loaders)) as executor:
        futures = {
            name: executor.submit(loader)
            for name, loader in loaders.items()
        }
        for name, future in futures.items():
            try:
                results[name] = future.result()
            except (Rent591Error, HousefunError) as exc:
                errors.append(f"{name}：{exc}")

    properties = merge_and_dedupe_properties(
        [results.get("591租屋", []), results.get("好房網快租", [])]
    )
    if not properties:
        raise Rent591Error(
            "目前所有租屋來源都無法取得房源。"
            + (" ".join(errors) if errors else "")
        )
    return properties


def load_properties_for_requirements(
    req: UserRequirements,
    plan: SourceSearchPlan | None = None,
) -> list[Property]:
    if req.property_source == "demo":
        return load_properties()
    if req.property_source == "591":
        planned_req = req.model_copy(
            update={
                "destination": (
                    plan.resolved_address
                    if plan and plan.resolved_address
                    else req.destination
                )
            }
        )
        return fetch_591_properties(planned_req)
    return _load_multi_source(
        req,
        plan or build_source_search_plan(req),
    )
