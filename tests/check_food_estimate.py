"""Exercise photo estimates and account-owned credentials without network access."""

import json
import runpy
from datetime import datetime
from unittest.mock import patch

import httpx

from tests.support import TestClient, sign_in

state = runpy.run_path("tests/check_sections.py")
app, models, database = state["app"], state["models"], state["database"]

key = "sk-project-pretend-key-for-tests-only"
other_key = "sk-project-another-test-key-never-used"
details = {
    "name": "Chicken and rice",
    "description": "Half a cup of rice",
    "timestamp": "2026-11-07T18:20",
    "client_timezone": "America/Chicago",
}
photo = {"photo": ("meal.jpg", b"\xff\xd8\xffphoto\xff\xd9", "image/jpeg")}
estimate = dict(calories=420, carbs=48, protein=36, fat=10, portion_note="One plate.")


def openai_result(values):
    return httpx.Response(
        200,
        json={
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": json.dumps(values)}],
                }
            ],
        },
    )


with TestClient(app) as client, patch("app.services.food_estimate.httpx.post") as post:
    assert client.get("/food/estimate", follow_redirects=False).status_code == 303
    sign_in(client)
    assert 'href="/food/estimate"' in client.get("/").text
    assert "Set up AI food estimates" in client.get("/food/estimate").text
    assert client.post("/food/estimate", data=details, files=photo).status_code == 409
    assert not post.called
    assert (
        client.request(
            "POST", "/settings/ai-food/key", data={"api_key": key}
        ).status_code
        == 403
    )
    assert (
        client.post("/settings/ai-food/key", data={"api_key": "invalid"}).status_code
        == 422
    )
    assert (
        client.post(
            "/settings/ai-food/key", data={"api_key": key}, follow_redirects=False
        ).status_code
        == 303
    )
    settings_page = client.get("/settings").text
    assert (
        "Your account has a saved API key" in settings_page and key not in settings_page
    )
    with database.SessionLocal() as db:
        credential = db.get(models.OpenAICredential, 1)
        assert key not in credential.encrypted_key

    sign_in(client, 2)
    assert "Set up AI food estimates" in client.get("/food/estimate").text
    assert client.post("/food/estimate", data=details, files=photo).status_code == 409
    assert not post.called
    assert (
        client.post("/settings/ai-food/remove", follow_redirects=False).status_code
        == 303
    )

    sign_in(client)
    assert 'id="open-camera"' in client.get("/food/estimate").text
    bad_photo = {"photo": ("fake.jpg", b"invalid", "image/jpeg")}
    assert (
        client.post("/food/estimate", data=details, files=bad_photo).status_code == 422
    )
    large_photo = {"photo": ("large.jpg", b"x" * (900 * 1024 + 1), "image/jpeg")}
    assert (
        client.post("/food/estimate", data=details, files=large_photo).status_code
        == 413
    )
    assert not post.called

    post.return_value = httpx.Response(429, json={"error": {"message": key}})
    result = client.post("/food/estimate", data=details, files=photo)
    assert result.status_code == 429 and key not in result.text
    post.return_value = openai_result(dict(estimate, calories=-1))
    assert client.post("/food/estimate", data=details, files=photo).status_code == 502
    post.return_value = openai_result(estimate)
    result = client.post("/food/estimate", data=details, files=photo)
    assert result.json() == estimate, result.text
    args, kwargs = post.call_args
    assert args == ("https://api.openai.com/v1/responses",)
    assert kwargs["headers"]["Authorization"] == f"Bearer {key}"
    payload = kwargs["json"]
    assert payload["store"] is False
    text, image = payload["input"][0]["content"]
    assert json.loads(text["text"]) == {
        "name": details["name"],
        "description": details["description"],
        "meal_time": "2026-11-08T00:20:00Z",
    }
    assert image["image_url"].startswith("data:image/jpeg;base64,")
    with database.SessionLocal() as db:
        assert (
            not db.query(models.FoodEntry)
            .filter_by(user_id=1, timestamp=datetime(2026, 11, 8, 0, 20))
            .count()
        )

    values = dict(
        details, **{k: estimate[k] for k in ("calories", "carbs", "protein", "fat")}
    )
    assert (
        client.post("/food/estimate/log", data=dict(values, carbs=-1)).status_code
        == 422
    )
    assert (
        client.post(
            "/food/estimate/log", data=dict(values, carbs=40), follow_redirects=False
        ).status_code
        == 303
    )
    with database.SessionLocal() as db:
        entry = (
            db.query(models.FoodEntry)
            .filter_by(user_id=1, timestamp=datetime(2026, 11, 8, 0, 20))
            .one()
        )
        assert entry.user_id == 1 and entry.food_item_id is None
        assert entry.timestamp == datetime(2026, 11, 8, 0, 20)
        assert entry.nutrition_snapshot["totals"]["carbs"] == 40
        assert entry.nutrition_snapshot["source"] == "ai_estimate"
        entry_id = entry.id
    assert details["name"] in client.get("/food").text
    assert client.get(f"/entries/food/{entry_id}/edit").status_code == 200
    assert (
        client.post(
            "/settings/ai-food/key", data={"api_key": other_key}, follow_redirects=False
        ).status_code
        == 303
    )
    assert client.post("/food/estimate", data=details, files=photo).status_code == 200
    assert post.call_args.kwargs["headers"]["Authorization"] == f"Bearer {other_key}"
    assert (
        client.post("/settings/ai-food/remove", follow_redirects=False).status_code
        == 303
    )
    assert client.post("/food/estimate", data=details, files=photo).status_code == 409

print("PASS: account-owned photo estimates, provider errors, and reviewed food logging")
