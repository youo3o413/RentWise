import socket

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.models.schemas import UserRequirements
from app.services.mock_property_service import load_mock_properties
from app.services.property_service import load_properties_for_requirements
from app.agents.rule_agents import property_assessment, _policy_preference_check


@pytest.fixture
def mock_only(monkeypatch):
    monkeypatch.setattr(get_settings(), "openai_api_key", "")
    monkeypatch.setattr(get_settings(), "live_listing_sources_enabled", False)


def test_fixture_is_diverse_and_does_not_link_to_real_listings():
    properties = load_mock_properties(UserRequirements())
    assert len(properties) == 18
    assert len({p.id for p in properties}) == len(properties)
    assert {p.has_window for p in properties} == {True, False, None}
    assert {p.has_elevator for p in properties} == {True, False, None}
    assert {p.rental_subsidy_eligible for p in properties} == {True, False, None}
    for p in properties:
        assert not p.source_url and not p.source_links and not p.image_url and not p.image_urls
        assert "虛構" in p.description
        assert p.latitude and p.longitude and p.listing_text
    req = UserRequirements(preferences=["可養寵物", "可開伙"])
    statuses = {label: set() for label in req.preferences}
    for p in properties:
        for check in property_assessment(p, req).checks:
            if check.label in statuses:
                statuses[check.label].add(check.status)
    assert all(values == {"met", "unmet", "unknown"} for values in statuses.values())


@pytest.mark.parametrize("source", ["mock", "591", "multi"])
def test_disabled_live_sources_never_call_scrapers(monkeypatch, mock_only, source):
    def forbidden(*args, **kwargs):
        pytest.fail("Live listing source was called")
    monkeypatch.setattr("app.services.property_service.fetch_591_properties", forbidden)
    monkeypatch.setattr("app.services.property_service.fetch_housefun_properties", forbidden)
    assert len(load_properties_for_requirements(UserRequirements(property_source=source))) == 18


def test_fixture_objects_and_commute_modes_are_independent():
    walk = load_mock_properties(UserRequirements(destination="台灣大學"))
    drive = load_mock_properties(UserRequirements(destination="台灣大學", commute_mode="drive"))
    assert walk[0].commute_minutes == walk[0].walking_commute_minutes
    assert drive[0].commute_minutes == drive[0].driving_commute_minutes
    walk[0].rent = 1
    assert load_mock_properties(UserRequirements())[0].rent != 1
    elsewhere = load_mock_properties(UserRequirements(destination="政治大學"))
    assert all(p.commute_minutes is None and p.walking_commute_minutes is None for p in elsewhere)


@pytest.mark.parametrize(("preference", "text", "status"), [
    ("可開伙", "不可開伙，無廚房。", "unmet"),
    ("可開伙", "可開伙，附獨立廚房。", "met"),
    ("可開伙", "可開伙，但僅限電磁爐，不可明火。", "unknown"),
    ("可養寵物", "可養貓、可養狗、可養寵物，寵物友善。", "met"),
    ("可養寵物", "不可養寵物，禁止貓狗。", "unmet"),
    ("可養寵物", "僅限一隻貓，需房東同意。", "unknown"),
    ("可養狗", "可養貓；犬隻不接受。", "unmet"),
    ("可養貓", "可養貓，不可養狗。", "met"),
    ("可養寵物", "寵物政策尚未提供。", "unknown"),
])
def test_pet_and_cooking_rules_respect_restrictions(preference, text, status):
    assert _policy_preference_check(preference, text, "示範資料").status == status


def test_mock_recommendations_change_with_needs_without_network(monkeypatch, mock_only):
    attempted_connections = []
    def forbidden_socket(*args, **kwargs):
        attempted_connections.append(True)
        raise AssertionError("Mock recommendation must not access network")
    monkeypatch.setattr(socket.socket, "connect", forbidden_socket)
    client = TestClient(app)
    shared = {"destination": "台大", "property_source": "multi", "noise_preference": "no_preference", "max_floor_without_elevator": 6}
    budget_response = client.post("/api/recommend", json={**shared, "budget": 11000, "needs_window": False})
    pets_response = client.post("/api/recommend", json={**shared, "budget": 25000, "max_commute_minutes": 40, "preferences": ["可養寵物", "可開伙"]})
    assert budget_response.status_code == pets_response.status_code == 200
    budget, pets = budget_response.json(), pets_response.json()
    assert len(budget["results"]) == len(pets["results"]) == 18
    assert pets["property_source"] == "mock"
    assert budget["results"][0]["property"]["id"] != pets["results"][0]["property"]["id"]
    winner = pets["results"][0]
    assert winner["assessments"]["suitability"]["metrics"]["qualification_status"] == "qualified"
    assert all(c["status"] == "met" for c in winner["assessments"]["property"]["checks"] if c["label"] in ["可養寵物", "可開伙"])
    assert pets["awaiting_feedback"]
    feedback = client.post(f'/api/recommend/{pets["thread_id"]}/feedback', json={"accepted": True})
    assert feedback.status_code == 200 and feedback.json()["workflow_status"] == "completed"
    assert not attempted_connections
