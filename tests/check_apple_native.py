"""Native export security/atomicity and resumable, account-scoped Shortcuts batches."""

import io
import re
import runpy
import zipfile
from datetime import timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient as RawClient
from sqlalchemy import create_engine, inspect, select

from tests.support import TestClient, sign_in

state = runpy.run_path("tests/check_sections.py")
app, models, database = state["app"], state["models"], state["database"]

from app.core import security
from app.db.migrations import schema_migrations
from app.db.migrations.shortcuts import NAME, apply_shortcut_migration
from app.services.apple_health import stamp
from app.services.apple_shortcuts import make_plan, now_utc

PREFIX = "/integrations/apple-health"
SHORT = PREFIX + "/shortcuts/"


def make_zip(xml, name="apple_health_export/export.xml"):
    file = io.BytesIO()
    with zipfile.ZipFile(file, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(name, xml)
    return file.getvalue()


def record(
    value="20",
    kind="HKQuantityTypeIdentifierStepCount",
    unit="count",
    start="2026-10-01 10:00:00 +0000",
):
    return f'<Record type="{kind}" sourceName="Fixture Watch" unit="{unit}" value="{value}" startDate="{start}" endDate="{start}"/>'


xml = (
    """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE HealthData [<!ELEMENT HealthData ANY>]><HealthData>
<Record type="HKCategoryTypeIdentifierSleepAnalysis" sourceName="Fixture Watch" value="HKCategoryValueSleepAnalysisAsleepCore" startDate="2026-10-01 02:00:00 +0000" endDate="2026-10-01 04:00:00 +0000"/>
"""
    + record()
    + record("80", "HKQuantityTypeIdentifierBodyMass", "kg")
    + """
<Record type="HKQuantityTypeIdentifierBloodGlucose" value="123"/>
<Workout workoutActivityType="HKWorkoutActivityTypeWalking" sourceName="Fixture Watch" duration="30" durationUnit="min" startDate="2026-10-01 10:00:00 +0000" endDate="2026-10-01 10:30:00 +0000">
<WorkoutStatistics type="HKQuantityTypeIdentifierActiveEnergyBurned" sum="100" unit="kcal"/>
<WorkoutStatistics type="HKQuantityTypeIdentifierDistanceWalkingRunning" sum="1.609344" unit="km"/>
</Workout></HealthData>"""
)

with TestClient(app) as browser:
    sign_in(browser, 1)
    headers = {"Content-Type": "application/zip"}
    response = browser.post(
        PREFIX + "/native-import", content=make_zip(xml), headers=headers
    )
    assert response.status_code == 200, response.text
    assert (
        response.json()["sleep"] == 1
        and response.json()["metric"] == 2
        and response.json()["workout"] == 1
    )
    assert response.json()["unsupported"] == 1
    again = browser.post(
        PREFIX + "/native-import", content=make_zip(xml), headers=headers
    )
    assert again.status_code == 200 and again.json()["skipped"] == 4
    offset_xml = xml.replace(
        "2026-10-01 10:00:00 +0000", "2026-10-01 05:00:00 -0500"
    ).replace("2026-10-01 10:30:00 +0000", "2026-10-01 05:30:00 -0500")
    offset_result = browser.post(
        PREFIX + "/native-import", content=make_zip(offset_xml), headers=headers
    )
    assert offset_result.status_code == 200 and offset_result.json()["skipped"] == 4
    with database.SessionLocal() as db:
        workout = db.query(models.HealthWorkout).filter_by(user_id=1).one()
        assert (
            workout.active_duration_seconds == 1800
            and workout.distance_miles == 1
            and workout.energy_kcal == 100
        )
        assert db.query(models.HealthNativeImport).filter_by(user_id=1).count() == 3
        before = db.query(models.HealthMetricSample).count()
    # Failure after a flushed 500-row chunk must roll back the entire file and receipt.
    many = "".join(
        record(start=f"2026-09-01 {i // 3600:02}:{i // 60 % 60:02}:{i % 60:02} +0000")
        for i in range(501)
    )
    invalid = "<HealthData>" + many + record("-1") + "</HealthData>"
    failed = browser.post(
        PREFIX + "/native-import", content=make_zip(invalid), headers=headers
    )
    assert failed.status_code == 400
    with database.SessionLocal() as db:
        assert db.query(models.HealthMetricSample).count() == before
        assert db.query(models.HealthNativeImport).filter_by(user_id=1).count() == 3
    for data in (
        b"not a zip",
        make_zip("<HealthData>" + ("<x>" * 80) + ("</x>" * 80) + "</HealthData>"),
        make_zip("<HealthData><Record></HealthData>"),
        make_zip(
            '<!DOCTYPE HealthData [<!ENTITY secret SYSTEM "file:///etc/passwd">]><HealthData>&secret;</HealthData>'
        ),
        make_zip("<HealthData/>", "../export.xml"),
    ):
        assert (
            browser.post(
                PREFIX + "/native-import", content=data, headers=headers
            ).status_code
            == 400
        )
    with patch.object(security, "NATIVE_HEALTH_BODY_LIMIT", 1024):
        assert (
            browser.post(
                PREFIX + "/native-import", content=b"x" * 1025, headers=headers
            ).status_code
            == 413
        )
    page = browser.get(PREFIX)
    assert (
        "No paid export app" in page.text
        and "Last Apple Health file imported:" in page.text
    )
    assert "Health Auto Export" not in page.text and "Premium" not in page.text
    assert browser.get(SHORT + "setup").status_code == 200
    token_page = browser.post(PREFIX + "/token")
    token = re.search(
        r'id="health-authorization"[^>]*value="Bearer ([^"]+)"', token_page.text
    ).group(1)
    with RawClient(app) as phone:
        phone.headers["Authorization"] = "Bearer " + token
        assert (
            phone.post(
                SHORT + "plan", json={"metric": "steps", "on_wifi": False}
            ).status_code
            == 400
        )
        plan = phone.post(
            SHORT + "plan", json={"metric": "steps", "on_wifi": True}
        ).json()
        assert plan["status"] == "ready"
        start = stamp(plan["start"])
        rows = [
            {
                "start": (start + timedelta(seconds=i)).isoformat() + "Z",
                "end": (start + timedelta(seconds=i + 1)).isoformat() + "Z",
                "value": i + 1,
                "unit": "count",
                "source": "Fixture Watch",
            }
            for i in range(201)
        ]
        batch = {"plan": plan["plan"], "index": 0, "records": rows[:200]}
        first = phone.post(SHORT + "batch", json=batch)
        assert first.status_code == 200, first.text
        assert phone.post(SHORT + "batch", json=batch).json()["repeated"]
        different = dict(batch, records=rows[1:201])
        assert phone.post(SHORT + "batch", json=different).status_code == 409
        completion = {"plan": plan["plan"], "batches": 2, "records": 201}
        assert phone.post(SHORT + "complete", json=completion).status_code == 409
        with database.SessionLocal() as db:
            assert db.query(models.HealthShortcutProgress).count() == 0
        assert (
            phone.post(
                SHORT + "batch",
                json={"plan": plan["plan"], "index": 1, "records": rows[200:]},
            ).status_code
            == 200
        )
        finished = phone.post(SHORT + "complete", json=completion)
        assert finished.status_code == 200, finished.text
        assert phone.post(SHORT + "complete", json=completion).json()["repeated"]
        second = phone.post(
            SHORT + "plan", json={"metric": "steps", "on_wifi": True}
        ).json()
        assert (
            phone.post(
                SHORT + "complete",
                json={"plan": second["plan"], "batches": 0, "records": 0},
            ).status_code
            == 200
        )
        assert (
            phone.post(
                SHORT + "plan", json={"metric": "steps", "on_wifi": True}
            ).json()["status"]
            == "up_to_date"
        )
        # Invalid dates, units, changed/foreign plans, and overlarge batches do not write.
        assert (
            phone.post(SHORT + "batch", json=dict(batch, records=rows)).status_code
            == 400
        )
        assert (
            phone.post(
                SHORT + "batch", json=dict(batch, plan=plan["plan"] + "tampered")
            ).status_code
            == 400
        )
        assert (
            phone.post(
                PREFIX + "/native-import",
                content=make_zip(xml),
                headers=headers,
                follow_redirects=False,
            ).status_code
            == 303
        )
        with database.SessionLocal() as db:
            assert db.query(models.HealthMetricSample).filter_by(user_id=2).count() == 0
        browser.post(PREFIX + "/revoke")
        assert (
            phone.post(
                SHORT + "plan", json={"metric": "steps", "on_wifi": True}
            ).status_code
            == 401
        )
    sign_in(browser, 2)
    assert "Last Apple Health file imported:" not in browser.get(PREFIX).text

with RawClient(app) as missing_csrf:
    sign_in(missing_csrf, 1)
    assert (
        missing_csrf.post(
            PREFIX + "/native-import",
            content=make_zip(xml),
            headers={"Content-Type": "application/zip"},
        ).status_code
        == 403
    )
    assert (
        missing_csrf.post(
            SHORT + "plan", json={"metric": "steps", "on_wifi": True}
        ).status_code
        == 401
    )

engine = create_engine("sqlite://")
models.User.__table__.create(engine)
schema_migrations.create(engine)
apply_shortcut_migration(engine, schema_migrations)
apply_shortcut_migration(engine, schema_migrations)
assert {
    "health_shortcut_progress",
    "health_shortcut_batches",
    "health_native_imports",
} <= set(inspect(engine).get_table_names())
with engine.connect() as db:
    assert db.execute(
        select(schema_migrations.c.name).where(schema_migrations.c.name == NAME)
    ).scalars().all() == [NAME]
assert make_plan(1, 1, "sleep", now=now_utc())["batch_size"] == 200
print(
    "PASS: native ZIP streaming, supported records/workouts, repeated imports, full-file rollback, XML/ZIP guards, CSRF/account isolation, batch retry/completion/checkpoints, key revocation, and repeat-safe migration."
)
