"""Check scoped health ingestion, atomic records, units, repeat safety and sleep union."""

import hashlib
import re
import runpy
from copy import deepcopy
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient as RawClient

from tests.support import TestClient, sign_in

state = runpy.run_path("tests/check_sections.py")
app, models, database = state["app"], state["models"], state["database"]
from app.services.apple_health import asleep_seconds

anchor = datetime.now(timezone.utc) - timedelta(days=2)


def date(hour):
    return (anchor + timedelta(hours=hour)).isoformat()


def sleep(stage, start, end):
    return dict(start=date(start), end=date(end), value=stage, source="Apple Watch")


payload = {
    "data": {
        "metrics": [
            {
                "name": "sleep_analysis",
                "units": "hr",
                "data": [
                    sleep("In Bed", 0, 8),
                    sleep("Core", 1, 3),
                    sleep("Deep", 3, 4),
                    sleep("REM", 4, 5),
                    sleep("Asleep", 1.5, 2.5),
                    sleep("Awake", 5, 5.5),
                ],
            },
            {
                "name": "step_count",
                "units": "count",
                "data": [{"date": date(8), "qty": 1000, "source": "Apple Watch"}],
            },
            {
                "name": "active_energy",
                "units": "kJ",
                "data": [{"date": date(8), "qty": 418.4, "source": "Apple Watch"}],
            },
            {
                "name": "weight_body_mass",
                "units": "kg",
                "data": [{"date": date(8), "qty": 80, "source": "Scale"}],
            },
            {
                "name": "resting_heart_rate",
                "units": "count/min",
                "data": [{"date": date(8), "qty": 60}],
            },
            {
                "name": "heart_rate_variability",
                "units": "s",
                "data": [{"date": date(8), "qty": 0.05}],
            },
            {
                "name": "heart_rate",
                "units": "count/min",
                "data": [{"date": date(8), "Min": 65, "Avg": 70, "Max": 75}],
            },
            {
                "name": "blood_glucose",
                "units": "mg/dL",
                "data": [{"date": date(8), "qty": 150}],
            },
        ],
        "workouts": [
            dict(
                id="workout-fixture",
                name="Walking",
                start=date(6),
                end=date(7),
                duration=3000,
                source={"name": "Apple Watch"},
                activeEnergyBurned={"qty": 200, "units": "kcal"},
                distance={"qty": 1.609344, "units": "km"},
            )
        ],
    }
}


def token_from(response):
    assert response.status_code == 200, response.text
    match = re.search(
        r'id="health-authorization"[^>]*value="Bearer ([^"]+)"', response.text
    )
    assert match, response.text
    return match.group(1)


with TestClient(app) as browser:
    sign_in(browser, 1)
    assert browser.get("/sleep").status_code == 200
    token = token_from(browser.post("/integrations/apple-health/token"))
    assert token not in browser.get("/integrations/apple-health").text
    with database.SessionLocal() as db:
        stored = (
            db.query(models.HealthImportToken).filter_by(user_id=1, active=True).one()
        )
        assert (
            stored.token_hash == hashlib.sha256(token.encode()).hexdigest()
            and stored.token_hash != token
        )
        before_glucose = db.query(models.GlucoseReading).count()
    with RawClient(app) as uploader:

        def upload(body=payload, credential=token, extra=None):
            return uploader.post(
                "/integrations/apple-health/import",
                json=body,
                headers={"Authorization": "Bearer " + credential, **(extra or {})},
            )

        assert (
            uploader.post("/integrations/apple-health/import", json=payload).status_code
            == 401
        )
        assert (
            uploader.get(
                "/sleep",
                headers={
                    "Authorization": "Bearer " + token,
                    "Accept": "application/json",
                },
            ).status_code
            == 401
        )
        sign_in(uploader, 2)
        assert (
            uploader.post("/integrations/apple-health/import", json=payload).status_code
            == 401
        )
        assert uploader.post("/integrations/apple-health/token").status_code == 403
        first = upload()
        assert first.status_code == 200, first.text
        assert first.json() == {
            "status": "ok",
            "sleep": 6,
            "metric": 6,
            "workout": 1,
            "updated": 0,
            "skipped": 0,
            "ignored": 1,
        }
        assert upload().json()["skipped"] == 13
        with database.SessionLocal() as db:
            rows = db.query(models.SleepInterval).filter_by(user_id=1).all()
            assert asleep_seconds(rows) == 4 * 3600
            assert db.query(models.SleepInterval).filter_by(user_id=2).count() == 0
            values = {
                r.metric: r.value
                for r in db.query(models.HealthMetricSample).filter_by(user_id=1)
            }
            assert abs(values["body_weight"] - 176.3698097479) < 0.0001
            assert (
                abs(values["active_energy"] - 100) < 0.000001
                and values["heart_rate_variability"] == 50
            )
            assert db.query(models.GlucoseReading).count() == before_glucose
            workout = db.query(models.HealthWorkout).filter_by(user_id=1).one()
            assert abs(workout.distance_miles - 1) < 0.00001
            assert workout.active_duration_seconds == 3000
        changed = deepcopy(payload)
        changed["data"]["metrics"][1]["data"][0]["qty"] = 1001
        assert upload(changed).json()["updated"] == 1
        for body in (
            {
                "data": {
                    "metrics": [
                        {
                            "name": "sleep_analysis",
                            "units": "hr",
                            "data": [{"date": date(1), "totalSleep": 8}],
                        }
                    ]
                }
            },
            {
                "data": {
                    "metrics": [
                        {
                            "name": "step_count",
                            "units": "count",
                            "data": [{"date": date(1), "qty": -1}],
                        }
                    ]
                }
            },
            {
                "data": {
                    "metrics": [
                        {
                            "name": "step_count",
                            "units": "count",
                            "data": [{"date": "2026-11-01 10:00:00", "qty": 1}],
                        }
                    ]
                }
            },
        ):
            assert upload(body).status_code == 400
        invalid = deepcopy(payload)
        invalid["data"]["metrics"][0]["data"].append(sleep("Core", 9, 10))
        invalid["data"]["metrics"][6]["data"][0]["Avg"] = float("inf")
        # Use a JSON-serializable invalid quantity to check full-request rollback.
        invalid["data"]["metrics"][6]["data"][0]["Avg"] = "Infinity"
        assert upload(invalid).status_code == 400
        with database.SessionLocal() as db:
            assert db.query(models.SleepInterval).filter_by(user_id=1).count() == 6
            db.query(models.SleepInterval).filter_by(
                user_id=1, stage="core"
            ).one().active = False
            db.commit()
        assert upload(changed).json()["skipped"] == 13
        assert upload(extra={"automation-aggregation": "Day"}).status_code == 400
        assert upload({"data": {"workouts": []}}).status_code == 200
        oversized = uploader.post(
            "/integrations/apple-health/import",
            content=b"x" * (1024 * 1024 + 1),
            headers={
                "Authorization": "Bearer " + token,
                "Content-Type": "application/json",
            },
        )
        assert oversized.status_code == 413
        replacement = token_from(browser.post("/integrations/apple-health/token"))
        assert upload(credential=token).status_code == 401
        assert upload(credential=replacement).status_code == 200
        browser.post("/integrations/apple-health/revoke")
        assert upload(credential=replacement).status_code == 401
        sign_in(browser, 2)
        second = token_from(browser.post("/integrations/apple-health/token"))
        assert upload(credential=second).json()["sleep"] == 6
        with database.SessionLocal() as db:
            db.get(models.User, 2).active = False
            db.commit()
        assert upload(credential=second).status_code == 401
    sign_in(browser, 1)
    assert "Recorded sleep:" in browser.get("/sleep").text
    assert browser.get("/sleep?days=8").status_code == 422
    assert "1000" in browser.get("/integrations/apple-health").text
print(
    "PASS: scoped hash-only tokens/rotation/revocation/account isolation; atomic uploads; duplicate/update handling; units; sleep union; summaries/naive times/body limits; sleep/activity pages."
)
