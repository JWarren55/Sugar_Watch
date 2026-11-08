"""Verify elapsed-time windows, UTC boundaries and account isolation."""

import runpy
from datetime import datetime, timedelta
from unittest.mock import patch

from sqlalchemy.exc import OperationalError

from tests.support import TestClient, sign_in

state = runpy.run_path("tests/check_sections.py")
app, models, database = state["app"], state["models"], state["database"]
from app.routes import glucose

now = datetime(2026, 11, 3, 1)
with database.SessionLocal() as db:
    for age in (25, 20, 12, 8, 6, 1, 0):
        db.add(
            models.GlucoseReading(
                user_id=1,
                glucose=100 + age,
                timestamp=now - timedelta(hours=age),
                active=True,
            )
        )
    db.add_all(
        [
            models.GlucoseReading(
                user_id=1,
                glucose=500,
                timestamp=now - timedelta(minutes=1),
                active=False,
            ),
            models.GlucoseReading(
                user_id=2,
                glucose=501,
                timestamp=now - timedelta(minutes=1),
                active=True,
            ),
            models.GlucoseReading(
                user_id=1,
                glucose=502,
                timestamp=now + timedelta(seconds=1),
                active=True,
            ),
        ]
    )
    db.commit()
with TestClient(app) as client, patch.object(glucose, "chart_now", return_value=now):
    assert (
        client.get(
            "/glucose/chart?hours=6", headers={"Accept": "application/json"}
        ).status_code
        == 401
    )
    sign_in(client, 1)
    page = client.get("/glucose")
    assert all(f'data-chart-hours="{hours}"' in page.text for hours in (6, 12, 24))
    assert "/static/glucose-chart.js" in page.text
    for hours, expected in ((6, 3), (12, 5), (24, 6)):
        response = client.get(f"/glucose/chart?hours={hours}")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        data = response.json()
        assert data["hours"] == hours and data["unit"] == "mg/dL"
        assert len(data["readings"]) == expected
        assert data["start"] == (now - timedelta(hours=hours)).isoformat() + "+00:00"
        assert data["end"] == now.isoformat() + "+00:00"
        assert (
            data["readings"][0]["time"] == data["start"] if hours in (6, 12) else True
        )
        assert all(point["glucose"] < 500 for point in data["readings"])
        assert [point["time"] for point in data["readings"]] == sorted(
            point["time"] for point in data["readings"]
        )
    assert client.get("/glucose/chart").json()["hours"] == 12
    for invalid in ("0", "7", "25", "24.5", "unknown"):
        assert client.get("/glucose/chart?hours=" + invalid).status_code == 422
    # History pagination must not restrict the plot.
    assert (
        len(client.get("/glucose/chart?hours=24&per_page=1&page=9").json()["readings"])
        == 6
    )
    sign_in(client, 2)
    assert [
        point["glucose"]
        for point in client.get("/glucose/chart?hours=6").json()["readings"]
    ] == [501]
    with patch.object(glucose, "chart_now", return_value=now + timedelta(days=10)):
        assert client.get("/glucose/chart?hours=24").json()["readings"] == []
    with patch.object(
        glucose,
        "SessionLocal",
        side_effect=OperationalError("fixture", {}, Exception("private")),
    ):
        response = client.get("/glucose/chart?hours=6")
        assert response.status_code == 503 and "private" not in response.text
print(
    "PASS: 6/12/24-hour UTC bounds; default/invalid/empty ranges; account and trash isolation; future exclusion; history-independent data; safe failures."
)
