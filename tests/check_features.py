"""Run from the project root: PYTHONPATH=. .venv/bin/python tests/check_features.py"""

import base64
import json
import runpy
from math import isclose
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from itsdangerous import TimestampSigner
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

# Load the application only after the test script configures its database.
state = runpy.run_path("tests/check_sections.py")
app, models, database = state["app"], state["models"], state["database"]

from routes.entries import SECTIONS

stamp = "2026-10-19T14:30"


def sign_in(client, user_id):
    client.cookies.clear()
    payload = base64.b64encode(json.dumps({"user_id": user_id}).encode())
    client.cookies.set(
        "session", TimestampSigner("integration-test").sign(payload).decode()
    )


with TestClient(app) as client:
    sign_in(client, 1)
    # Metric entry, storage, history, and edit must use the same conversions.
    response = client.post(
        "/health/profile",
        data={
            "height": 177.8,
            "sex": "Male",
            "date_of_birth": "1990-01-01",
            "preferred_units": "metric",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert (
        client.post(
            "/health/measurements",
            data={
                "timestamp": stamp,
                "weight": 100,
                "waist": 90,
                "measurement_units": "metric",
            },
            follow_redirects=False,
        ).status_code
        == 303
    )
    assert (
        client.post(
            "/exercise",
            data={
                "timestamp": stamp,
                "length_minutes": 30,
                "exercise_type": "Cardio",
                "intensity": "Medium",
                "distance": 5,
                "measurement_units": "metric",
            },
            follow_redirects=False,
        ).status_code
        == 303
    )
    with database.SessionLocal() as db:
        measurement = (
            db.query(models.HealthHistory)
            .order_by(models.HealthHistory.id.desc())
            .first()
        )
        exercise = (
            db.query(models.ExerciseEntry)
            .order_by(models.ExerciseEntry.id.desc())
            .first()
        )
        assert isclose(measurement.weight, 100 / 0.45359237)
        assert isclose(measurement.waist, 90 / 2.54)
        assert isclose(exercise.distance, 5 / 1.609344)
    assert "Weight (kg)" in client.get("/health").text
    assert "Distance (km)" in client.get("/exercise").text

    payloads = {
        "glucose": {"glucose": 155, "timestamp": stamp},
        "exercise": {
            "timestamp": stamp,
            "length_minutes": 45,
            "exercise_type": "Weights",
            "intensity": "Low",
            "average_heart_rate": "",
            "peak_heart_rate": "",
            "distance": 8,
            "measurement_units": "metric",
        },
        "medication": {
            "timestamp": stamp,
            "medication_name": "Edited medication",
            "dose": 5,
            "unit": "mg",
        },
        "mood": {"timestamp": stamp, "feeling": "Good", "hunger": "", "head": ""},
        "health": {
            "timestamp": stamp,
            "weight": 80,
            "waist": 85,
            "measurement_units": "metric",
        },
        "food": {"timestamp": stamp, "food_item_id": 1, "amount": 60, "unit": "g"},
        "food-item": {
            "name": "Edited oats",
            "brand": "Test",
            "serving_size": 40,
            "serving_unit": "g",
            "calories": 160,
        },
    }
    ids = {}
    for section, (model, title, back) in SECTIONS.items():
        with database.SessionLocal() as db:
            ids[section] = db.query(model).filter(model.user_id == 1).first().id
        entry_id = ids[section]
        page = client.get(f"/entries/{section}/{entry_id}/edit")
        assert page.status_code == 200 and "Save Changes" in page.text, (
            section,
            page.text,
        )
        result = client.post(
            f"/entries/{section}/{entry_id}/edit",
            data=payloads[section],
            follow_redirects=False,
        )
        assert result.status_code == 303, (section, result.text)
        page = client.get(back)
        assert page.status_code == 200
        assert f"/entries/{section}/{entry_id}/edit" in page.text
        assert f"/entries/{section}/{entry_id}/delete" in page.text
    with database.SessionLocal() as db:
        assert db.get(models.GlucoseReading, ids["glucose"]).glucose == 155
        assert isclose(
            db.get(models.ExerciseEntry, ids["exercise"]).distance, 8 / 1.609344
        )
        assert isclose(
            db.get(models.HealthHistory, ids["health"]).weight, 80 / 0.45359237
        )
        assert db.get(models.FoodItem, ids["food-item"]).calories == 160

    # Failed saves retain data and return a message suitable for inline display.
    bad = client.post(
        "/medication",
        data={"timestamp": stamp, "medication_name": "Test", "dose": 5, "unit": ""},
    )
    assert bad.status_code == 400 and "unit" in bad.json()["detail"][0]
    bad = client.post(
        "/glucose",
        data={"timestamp": "bad", "glucose": "bad"},
        headers={"Accept": "text/html"},
    )
    assert bad.status_code == 422 and "Check your entry" in bad.text
    bad = client.post(
        "/entries/health/1/edit",
        data={"timestamp": stamp, "weight": "nan", "waist": ""},
    )
    assert bad.status_code == 422
    with patch.object(
        Session,
        "commit",
        side_effect=OperationalError(
            "secret query", {}, Exception("secret credential")
        ),
    ):
        bad = client.post(
            "/medication", data={"timestamp": stamp, "medication_name": "Must not save"}
        )
        assert bad.status_code == 503 and "secret" not in bad.text
    with database.SessionLocal() as db:
        assert (
            db.query(models.MedicationEntry)
            .filter_by(medication_name="Must not save")
            .count()
            == 0
        )
        original_count = db.query(models.FoodEntry).count()
    bad = client.post(
        "/food/log-multiple",
        data={"food_item_id": [1, 1], "amount": [40, -1], "unit": ["g", "g"]},
    )
    assert bad.status_code == 422
    with database.SessionLocal() as db:
        assert db.query(models.FoodEntry).count() == original_count

    # Another user cannot read, modify, delete, log, or favorite these records.
    sign_in(client, 2)
    for section, entry_id in ids.items():
        for suffix in ("edit", "delete"):
            assert (
                client.get(f"/entries/{section}/{entry_id}/{suffix}").status_code == 404
            )
        assert (
            client.post(
                f"/entries/{section}/{entry_id}/edit", data=payloads[section]
            ).status_code
            == 404
        )
        assert client.post(f"/entries/{section}/{entry_id}/delete").status_code == 404
    assert (
        client.post(
            "/food/quick-log", data={"food_item_id": 1, "amount": 1, "unit": "g"}
        ).status_code
        == 404
    )
    assert client.post("/food/favorite", data={"food_item_id": 1}).status_code == 404
    assert (
        client.post(
            "/food/log-multiple", data={"food_item_id": 1, "amount": 1, "unit": "g"}
        ).status_code
        == 400
    )

    sign_in(client, 1)
    # Deletion only changes active, and confirmation GETs do not change data.
    for section, entry_id in ids.items():
        assert client.get(f"/entries/{section}/{entry_id}/delete").status_code == 200
        result = client.post(
            f"/entries/{section}/{entry_id}/delete", follow_redirects=False
        )
        assert result.status_code == 303
        with database.SessionLocal() as db:
            assert db.get(SECTIONS[section][0], entry_id).active is False
        assert client.get(f"/entries/{section}/{entry_id}/edit").status_code == 404

    # Canonicalize localhost before Google creates state, avoiding callback mismatch.
    result = client.get("http://localhost:8000/login", follow_redirects=False)
    assert (
        result.status_code == 307
        and result.headers["location"] == "http://127.0.0.1:8000/login"
    )

    # OAuth callback session handling can be checked without contacting Google.
    from routes import auth

    with patch.object(
        auth.oauth.google,
        "authorize_access_token",
        new=AsyncMock(
            return_value={
                "userinfo": {
                    "sub": "test1",
                    "email": "one@example.test",
                    "name": "Test One",
                }
            }
        ),
    ):
        client.cookies.clear()
        result = client.get("/auth/google/callback", follow_redirects=False)
        assert result.status_code == 307 and result.headers["location"] == "/"
        assert "Welcome" in client.get("/").text
    with patch.object(
        auth.oauth.google,
        "authorize_access_token",
        new=AsyncMock(side_effect=ValueError("cancelled")),
    ):
        assert (
            "cancelled"
            in client.get("/auth/google/callback", follow_redirects=False).headers[
                "location"
            ]
        )
    assert client.get("/logout", follow_redirects=False).is_redirect
    assert (
        client.get("/medication", follow_redirects=False).headers["location"]
        == "/login"
    )

print(
    "PASS: metric round trips; edit/delete for all sections; validation and outage errors; atomic food batches; ownership; mocked OAuth/session/logout."
)
