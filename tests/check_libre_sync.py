"""Mock the external service; exercise persistence on disposable test accounts."""

import runpy
from datetime import datetime

import httpx

from tests.support import TestClient, sign_in

state = runpy.run_path("tests/check_sections.py")
models, database, app = state["models"], state["database"], state["app"]

from app.services.libre_import import parse_libreview
from app.services.libre_sync import (
    SyncConfig,
    SyncError,
    fetch_readings,
    normalize_graph,
    save_readings,
)

config = SyncConfig(
    "follower@example.test", "fictional-password", "us", "4.16.0", "patient-fixture", 1
)
assert "fictional-password" not in repr(config)
point = {"FactoryTimestamp": "10/31/2026 03:15:00 PM", "ValueInMgPerDl": 123}
graph = {
    "connection": {"patientId": "patient-fixture", "glucoseMeasurement": point},
    "graphData": [point],
}
calls = []


def respond(request):
    calls.append(request.url.path)
    assert request.url.host == "api-us.libreview.io"
    assert request.headers["product"] == "llu.ios"
    if request.url.path.endswith("/login"):
        assert b"fictional-password" in request.content
        data = {
            "user": {"id": "account-fixture"},
            "authTicket": {"token": "fictional-token"},
        }
    else:
        assert request.headers["Authorization"] == "Bearer fictional-token"
        assert len(request.headers["account-id"]) == 64
        data = (
            [{"patientId": "patient-fixture"}]
            if request.url.path.endswith("/connections")
            else graph
        )
    return httpx.Response(200, json={"status": 0, "data": data})


with httpx.Client(transport=httpx.MockTransport(respond)) as client:
    rows = fetch_readings(config, client)
assert len(rows) == 1 and rows[0]["timestamp"] == datetime(2026, 10, 31, 15, 15)
assert len(calls) == 3
assert save_readings(database.SessionLocal, 1, rows) == (1, 0)
assert save_readings(database.SessionLocal, 1, rows) == (0, 1)
assert save_readings(database.SessionLocal, 2, rows) == (1, 0)
with database.SessionLocal() as db:
    record = (
        db.query(models.GlucoseReading).filter_by(user_id=1, source="librelinkup").one()
    )
    record.active = False
    db.commit()
assert save_readings(database.SessionLocal, 1, rows) == (0, 1)
try:
    save_readings(database.SessionLocal, 99999, rows)
except SyncError:
    pass
else:
    raise AssertionError("Missing target account accepted")

for status, body in (
    (429, {}),
    (403, {"secret": "do-not-log"}),
    (200, {"status": 4, "data": {"token": "do-not-log"}}),
    (200, {"status": 0, "data": {"redirect": True, "region": "eu"}}),
):
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(status, json=body))
    ) as client:
        try:
            fetch_readings(config, client)
        except SyncError as exc:
            assert "do-not-log" not in str(exc)
        else:
            raise AssertionError("Provider failure accepted")
for bad in (
    {"connection": {"patientId": "wrong"}, "graphData": [point]},
    {
        "connection": {"patientId": "patient-fixture"},
        "graphData": [dict(point, ValueInMgPerDl="NaN")],
    },
    {
        "connection": {"patientId": "patient-fixture"},
        "graphData": [point, dict(point, ValueInMgPerDl=124)],
    },
):
    try:
        normalize_graph(bad, config.patient_id)
    except SyncError:
        pass
    else:
        raise AssertionError("Unsafe provider reading accepted")

# Real export format: hyphenated month/day/year plus 12-hour clock.
csv = b"Device,Serial Number,Device Timestamp,Record Type,Historic Glucose mg/dL\nLibre 3,fake,10-31-2026 10:15 AM,0,120\n"
assert parse_libreview(csv, "America/Chicago", "MDY")[0][0]["timestamp"] == datetime(
    2026, 10, 31, 15, 15
)

# The import endpoint accepts a larger bounded file while all other forms stay at 1 MB.
with TestClient(app) as client:
    sign_in(client, 1)
    # Use many short metadata-free blank rows, not a single giant CSV field.
    large_csv = csv + b"\n" * (1024 * 1024)
    response = client.post(
        "/glucose/import/libreview",
        data={"timezone_name": "America/Chicago", "date_order": "MDY"},
        files={"file": ("fixture.csv", large_csv, "text/csv")},
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    response = client.post(
        "/glucose/import/libreview",
        data={"timezone_name": "UTC", "date_order": "MDY"},
        files={"file": ("fixture.csv", b"x" * (4 * 1024 * 1024), "text/csv")},
        follow_redirects=False,
    )
    assert response.status_code == 413
print(
    "PASS: mocked Libre authentication/fetch; UTC; patient/account mapping; rate/consent/error handling; duplicate and deleted protection; extended CSV format/body limits."
)
