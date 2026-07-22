from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_health():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_recommendation_returns_ranked_properties():
    response = client.post(
        "/api/recommend",
        json={
            "budget": 15000,
            "destination": "政治大學",
            "max_commute_minutes": 25,
            "needs_window": True,
            "noise_preference": "quiet",
            "needs_elevator": False,
            "needs_convenience_store": True,
            "max_floor_without_elevator": 3,
            "preferences": ["採光良好", "可開伙"],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["results"]) == 5
    assert body["results"][0]["rank"] == 1
    assert len(body["trace"]) >= 6
