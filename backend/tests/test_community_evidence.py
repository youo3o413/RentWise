from types import SimpleNamespace

from app.agents.community_evidence import (
    PUBLIC_COMMUNITY_DOMAINS,
    _search_property,
    collect_community_evidence,
    community_preferences,
)
from app.models.schemas import Property, UserRequirements


def _property() -> Property:
    return Property(
        id="listing-1",
        title="台大附近套房",
        address="台北市大安區新生南路",
        rent=15000,
        management_fee=0,
        water_fee=0,
        electricity_rate=5,
        estimated_kwh=100,
        commute_minutes=10,
        has_window=None,
        window_type="未揭露",
        has_elevator=None,
        floor=None,
        noise_level=None,
        nearby=[],
        features=[],
        risks=[],
        description="",
        image_url="https://example.com/room.jpg",
    )


def test_community_preferences_only_select_subjective_requirements():
    req = UserRequirements(
        preferences=["可養貓", "隔音良好", "可開伙"],
        property_source="demo",
    )

    assert community_preferences(req) == ["可養貓", "隔音良好"]


def test_disabled_community_evidence_never_calls_openai():
    evidence, message = collect_community_evidence(
        UserRequirements(
            preferences=["可養貓"],
            use_community_evidence=False,
            property_source="demo",
        ),
        [_property()],
    )

    assert evidence == {}
    assert message == "未啟用公開社群查證"


def test_search_keeps_web_citations_and_excludes_facebook():
    annotation = SimpleNamespace(
        url="https://www.ptt.cc/bbs/NTU/M.123.html",
        title="PTT 台大生活討論",
    )
    output = [
        SimpleNamespace(
            content=[
                SimpleNamespace(annotations=[annotation]),
            ]
        )
    ]

    class FakeResponses:
        def parse(self, **kwargs):
            domains = kwargs["tools"][0]["filters"]["allowed_domains"]
            assert domains == PUBLIC_COMMUNITY_DOMAINS
            assert all("facebook" not in domain for domain in domains)
            return SimpleNamespace(
                output=output,
                output_parsed=SimpleNamespace(
                    overview="找到街區寵物生活討論，但仍需向房東確認。",
                    findings=[
                        SimpleNamespace(
                            topic="可養貓",
                            sentiment="mixed",
                            scope="nearby_area",
                            summary="附近有養寵討論，個別房源仍需確認。",
                        )
                    ],
                ),
            )

    client = SimpleNamespace(responses=FakeResponses())
    evidence = _search_property(
        client,
        "gpt-4.1-mini",
        _property(),
        ["可養貓"],
    )

    assert evidence.status == "found"
    assert evidence.confidence == "low"
    assert evidence.sources[0].url.startswith("https://www.ptt.cc/")
    assert evidence.findings[0].scope == "nearby_area"
    assert evidence.findings[0].sentiment == "mixed"
    assert "租約" in evidence.disclaimer
