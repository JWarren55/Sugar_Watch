"""Verify dashboard ownership, local-day totals, and timed events."""

import runpy
from datetime import datetime, timedelta
from unittest.mock import patch

from tests.support import TestClient, sign_in

state = runpy.run_path("tests/check_sections.py")
app, models, database = state["app"], state["models"], state["database"]
from app.routes import dashboard_pages, glucose  # noqa: E402

now = datetime(2026, 11, 2, 15)
midnight = datetime(2026, 11, 2, 6)
with database.SessionLocal() as db:
    db.add_all(
        [
            models.FoodEntry(
                user_id=user_id,
                timestamp=stamp,
                amount=1,
                unit="serving",
                nutrition_snapshot={"name": name, "totals": {"calories": calories}},
                active=active,
            )
            for user_id, stamp, name, calories, active in (
                (1, midnight, "Breakfast", 250, True),
                (1, midnight - timedelta(seconds=1), "Previous day", 400, True),
                (1, now, "Deleted meal", 800, False),
                (2, midnight, "Private meal", 900, True),
            )
        ]
    )
    db.add_all(
        [
            models.ExerciseEntry(
                user_id=1,
                timestamp=now - timedelta(hours=7),
                length_minutes=120,
                exercise_type="Cardio",
                intensity="Low",
            ),
            models.SleepInterval(
                user_id=1,
                start_time=midnight - timedelta(hours=3),
                end_time=midnight + timedelta(hours=2),
                stage="asleep",
            ),
            models.SleepInterval(
                user_id=1,
                start_time=midnight + timedelta(hours=1),
                end_time=midnight + timedelta(hours=2),
                stage="deep",
            ),
            models.HealthMetricSample(
                user_id=1,
                metric="heart_rate",
                value=72,
                unit="bpm",
                start_time=now,
                end_time=now,
            ),
            models.HealthMetricSample(
                user_id=1,
                metric="active_energy",
                value=120,
                unit="kcal",
                start_time=midnight - timedelta(hours=1),
                end_time=midnight + timedelta(hours=1),
            ),
            models.HealthNativeImport(
                user_id=1, created_at=now - timedelta(minutes=5), counts={}
            ),
        ]
    )
    db.commit()

with (
    TestClient(app) as client,
    patch.object(dashboard_pages, "utc_now", return_value=now),
    patch.object(glucose, "chart_now", return_value=now),
):
    assert (
        client.get(
            "/dashboard/summary", headers={"Accept": "application/json"}
        ).status_code
        == 401
    )
    sign_in(client, 1)
    for path, text in (
        ("/", "Heart &amp; sleep"),
        ("/insight", "future update"),
        ("/settings", "Daily nutrition goals"),
    ):
        page = client.get(path)
        assert page.status_code == 200 and text in page.text

    goal = dict(calories=1800, carbs=220, protein=95, fat=60)
    assert (
        client.post(
            "/settings/nutrition", data=goal, follow_redirects=False
        ).status_code
        == 303
    )
    goal["calories"] = 2000
    assert (
        client.post(
            "/settings/nutrition", data=goal, follow_redirects=False
        ).status_code
        == 303
    )
    assert (
        client.post("/settings/nutrition", data={**goal, "fat": -1}).status_code == 422
    )
    summary = client.get("/dashboard/summary?zone=America/Chicago").json()
    assert summary["goals"] == goal
    assert summary["nutrition"] == {
        "calories": 250,
        "carbs": None,
        "protein": None,
        "fat": None,
    }
    assert summary["heart_rate"] == 72 and summary["active_energy"] == 60
    assert (
        summary["sleep_minutes"] == 120
        and summary["apple_updated"] == "2026-11-02T14:55:00Z"
    )
    assert (
        client.get("/dashboard/summary?zone=UTC").json()["nutrition"]["calories"] == 650
    )
    assert client.get("/dashboard/summary?zone=bad-zone").status_code == 422

    chart = client.get("/glucose/chart?hours=12&events=true").json()["timeline"]
    assert {event["label"] for event in chart["events"]} >= {
        "Breakfast",
        "Sleep",
        "Wake up",
        "Cardio",
    }
    assert all(
        event["label"] not in ("Private meal", "Deleted meal")
        for event in chart["events"]
    )
    clipped = client.get("/glucose/chart?hours=6&events=true").json()["timeline"]
    assert clipped["workouts"] == [
        {"start": "2026-11-02T09:00:00Z", "end": "2026-11-02T10:00:00Z"}
    ]
    logs = client.get("/logs?log=food").text
    assert (
        "Breakfast" in logs
        and "Deleted meal" not in logs
        and "Private meal" not in logs
    )
    assert client.get("/logs?log=health_import_tokens").status_code == 404

    sign_in(client, 2)
    summary = client.get("/dashboard/summary?zone=America/Chicago").json()
    assert summary["nutrition"]["calories"] == 900
    assert summary["goals"]["calories"] is None and summary["apple_updated"] == ""

print(
    "PASS: dashboard pages, goal updates, local-day totals, chart events, and account isolation."
)
