"""Check UTC storage, frozen nutrition, page controls, trash, and sign-in errors."""

import runpy
from datetime import datetime
from math import isclose
from unittest.mock import AsyncMock, patch

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from tests.support import TestClient, sign_in

state = runpy.run_path("tests/check_sections.py")
app, models, database = state["app"], state["models"], state["database"]
from app.routes import auth
from app.services.nutrition import canonical
from app.utils.time_utils import to_utc, utc_now


def post(client, path, data=None):
    response = client.post(path, data=data or {}, follow_redirects=False)
    assert response.status_code == 303, (path, response.status_code, response.text)
    return response


assert to_utc("2026-10-21T14:30:00-05:00") == datetime(2026, 10, 21, 19, 30)
assert to_utc("2026-01-21T14:30:00", "America/Chicago") == datetime(2026, 1, 21, 20, 30)
assert isclose(canonical(1, "lb")[0], 453.59237)

with TestClient(app) as client:
    sign_in(client)
    before = utc_now()
    post(client, "/glucose", {"glucose": 120})
    after = utc_now()
    post(client, "/glucose", {"glucose": 121, "timestamp": "2026-10-21T14:30:00-05:00"})
    with database.SessionLocal() as db:
        readings = (
            db.query(models.GlucoseReading)
            .order_by(models.GlucoseReading.id.desc())
            .limit(2)
            .all()
        )
        assert readings[0].timestamp == datetime(2026, 10, 21, 19, 30)
        assert before <= readings[1].timestamp <= after
    html = client.get("/glucose").text
    assert "2026-10-21T19:30:00Z" in html and 'class="local-time"' in html
    assert (
        client.post(
            "/glucose",
            data={
                "glucose": 130,
                "timestamp": "2026-03-08T02:30:00",
                "client_timezone": "America/Chicago",
            },
        ).status_code
        == 400
    )

    post(
        client,
        "/food/create",
        {
            "name": "Snapshot oats",
            "serving_size": 1,
            "serving_unit": "oz",
            "calories": 100,
            "protein": 4,
        },
    )
    with database.SessionLocal() as db:
        food = db.query(models.FoodItem).filter_by(name="Snapshot oats").one()
        food_id = food.id
        assert isclose(food.serving_size, 28.349523125)
        assert food.serving_unit == "g"
    post(
        client,
        "/food/quick-log",
        {
            "food_item_id": food_id,
            "amount": 2,
            "unit": "oz",
            "timestamp": "2026-10-21T14:30:00-05:00",
        },
    )
    with database.SessionLocal() as db:
        entry = db.query(models.FoodEntry).order_by(models.FoodEntry.id.desc()).first()
        entry_id = entry.id
        assert isclose(entry.amount, 56.69904625) and entry.unit == "g"
        assert entry.nutrition_snapshot["totals"]["calories"] == 200
        assert entry.nutrition_snapshot["totals"]["protein"] == 8
        assert entry.timestamp == datetime(2026, 10, 21, 19, 30)
    post(
        client,
        f"/entries/food-item/{food_id}/edit",
        {
            "name": "Renamed oats",
            "serving_size": 1,
            "serving_unit": "oz",
            "calories": 300,
            "protein": 9,
        },
    )
    with database.SessionLocal() as db:
        entry = db.get(models.FoodEntry, entry_id)
        assert entry.nutrition_snapshot["totals"]["calories"] == 200
        assert entry.nutrition_snapshot["name"] == "Snapshot oats"
    payload = {
        "food_item_id": food_id,
        "amount": 3,
        "unit": "oz",
        "timestamp": "2026-10-21T19:30:00Z",
    }
    post(client, f"/entries/food/{entry_id}/edit", payload)
    with database.SessionLocal() as db:
        assert isclose(
            db.get(models.FoodEntry, entry_id).nutrition_snapshot["totals"]["calories"],
            300,
        )
    post(
        client,
        f"/entries/food/{entry_id}/edit",
        dict(
            payload,
            nutrition_mode="manual",
            nutrition_calories=999,
            nutrition_protein=12,
        ),
    )
    with database.SessionLocal() as db:
        snapshot = db.get(models.FoodEntry, entry_id).nutrition_snapshot
        assert (
            snapshot["totals"]["calories"] == 999 and snapshot["totals"]["fat"] is None
        )
    post(client, f"/entries/food/{entry_id}/edit", dict(payload, amount=6))
    with database.SessionLocal() as db:
        assert isclose(
            db.get(models.FoodEntry, entry_id).nutrition_snapshot["totals"]["calories"],
            1998,
        )
    post(
        client,
        f"/entries/food/{entry_id}/edit",
        dict(payload, nutrition_mode="current"),
    )
    with database.SessionLocal() as db:
        snapshot = db.get(models.FoodEntry, entry_id).nutrition_snapshot
        assert (
            isclose(snapshot["totals"]["calories"], 900)
            and snapshot["name"] == "Renamed oats"
        )
    assert (
        client.post(
            "/food/quick-log",
            data={"food_item_id": food_id, "amount": 1, "unit": "cup"},
        ).status_code
        == 400
    )
    assert (
        client.post(
            f"/entries/food/{entry_id}/edit",
            data=dict(payload, nutrition_mode="manual", nutrition_calories=-1),
        ).status_code
        == 400
    )

    # Paging handles ties, impossible pages, independent saved foods, and invalid input.
    with database.SessionLocal() as db:
        db.add_all(
            [
                models.GlucoseReading(
                    user_id=1,
                    timestamp=datetime(2026, 10, 22),
                    glucose=200 + index,
                    active=True,
                )
                for index in range(31)
            ]
        )
        db.commit()
    first = client.get("/glucose?per_page=10")
    second = client.get("/glucose?per_page=10&page=2")
    assert "Page 1 of 4" in first.text and "Page 2 of 4" in second.text
    assert "230" in first.text and "230" not in second.text
    assert "Next" in first.text and "Previous" in second.text
    assert client.get("/glucose?per_page=999").status_code == 400
    assert client.get("/glucose?page=-1").status_code == 400
    assert client.get("/glucose?page=999&per_page=10").status_code == 200
    assert client.get("/food?foods_page=2&foods_per_page=10&page=1").status_code == 200

    # Only inactive owned records can be restored or permanently deleted.
    assert client.get("/trash").status_code == 200
    assert (
        client.post(
            f"/entries/food-item/{food_id}/purge", data={"confirmation": "DELETE"}
        ).status_code
        == 404
    )
    post(client, f"/entries/food-item/{food_id}/delete")
    assert "Renamed oats" in client.get("/trash?section=food-item").text
    assert (
        client.post(
            f"/entries/food-item/{food_id}/purge", data={"confirmation": "wrong"}
        ).status_code
        == 400
    )
    post(client, f"/entries/food-item/{food_id}/restore")
    assert "Renamed oats" in client.get("/food").text
    post(client, f"/entries/food-item/{food_id}/delete")
    post(client, f"/entries/food-item/{food_id}/purge", {"confirmation": "DELETE"})
    with database.SessionLocal() as db:
        assert db.get(models.FoodItem, food_id) is None
        entry = db.get(models.FoodEntry, entry_id)
        assert entry.food_item_id is None and isclose(
            entry.nutrition_snapshot["totals"]["calories"], 900
        )
    assert "Renamed oats" in client.get("/food").text
    post(
        client,
        f"/entries/food/{entry_id}/edit",
        dict(payload, food_item_id="", nutrition_mode="manual", nutrition_calories=700),
    )
    assert 'class="local-time"' in client.get(f"/entries/food/{entry_id}/delete").text
    post(client, f"/entries/food/{entry_id}/delete")
    sign_in(client, 2)
    assert "Renamed oats" not in client.get("/trash").text
    for suffix in ("restore", "purge"):
        assert (
            client.post(
                f"/entries/food/{entry_id}/{suffix}", data={"confirmation": "DELETE"}
            ).status_code
            == 404
        )
    sign_in(client)
    post(client, f"/entries/food/{entry_id}/purge", {"confirmation": "DELETE"})
    with database.SessionLocal() as db:
        assert db.get(models.FoodEntry, entry_id) is None

    client.cookies.clear()
    result = client.post(
        "/glucose", data={"glucose": 120}, headers={"Accept": "application/json"}
    )
    assert result.status_code == 401 and "expired" in result.text
    for error, expected in (
        ("access_denied", "cancelled"),
        ("invalid_request", "provider"),
    ):
        assert (
            expected
            in client.get(
                "/auth/google/callback?error=" + error, follow_redirects=False
            ).headers["location"]
        )
    with patch.object(
        auth.oauth.google,
        "authorize_access_token",
        new=AsyncMock(
            return_value={
                "userinfo": {
                    "email_verified": True,
                    "sub": "test1",
                    "email": "one@example.test",
                }
            }
        ),
    ):
        with patch.object(
            Session,
            "scalar",
            side_effect=OperationalError("private SQL", {}, Exception("secret")),
        ):
            result = client.get("/auth/google/callback", follow_redirects=False)
            assert (
                "database" in result.headers["location"] and "secret" not in result.text
            )
    with patch.object(
        auth.oauth.google,
        "authorize_access_token",
        new=AsyncMock(
            return_value={
                "userinfo": {
                    "email_verified": True,
                }
            }
        ),
    ):
        assert (
            "profile"
            in client.get("/auth/google/callback", follow_redirects=False).headers[
                "location"
            ]
        )
    assert "database could not complete" in client.get("/?login=database").text

print(
    "PASS: UTC and DST; immutable/editable nutrition; compatible units; paging; trash/restore/purge; owner isolation; specific sign-in errors."
)
