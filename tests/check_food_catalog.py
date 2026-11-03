"""USDA units, reviewed imports, CSRF, ownership, repeated saves and failures."""

import re
import runpy
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient as RawClient

from tests.support import TestClient, sign_in

state = runpy.run_path("tests/check_sections.py")
app, models, database = state["app"], state["models"], state["database"]

from itsdangerous import SignatureExpired

from food_catalog import CatalogError, USDAClient, food_values
from routes import food_catalog as routes


def nutrient(id, amount, unit):
    return {"nutrient": {"id": id, "unitName": unit}, "amount": amount}


raw = dict(
    fdcId=123456,
    dataType="Branded",
    description="Fixture oats",
    brandName="Fixture Brand",
    gtinUpc="0123456789",
    servingSize=30,
    servingSizeUnit="g",
    foodNutrients=[
        nutrient(1008, 400, "KCAL"),
        nutrient(2047, 401, "KCAL"),
        nutrient(1005, 60, "G"),
        nutrient(1003, 10, "G"),
        nutrient(1004, 8, "G"),
        nutrient(1093, 0.2, "G"),
        nutrient(1114, 2, "UG"),
    ],
)
values = food_values(raw)
assert values["serving_size"] == 100 and values["serving_unit"] == "g"
assert (
    values["calories"] == 400 and values["sodium"] == 200 and values["vitamin_d"] == 2
)
assert values["sugar"] is None
for invalid in (float("nan"), -1, True):
    try:
        food_values(dict(raw, foodNutrients=[nutrient(1008, invalid, "KCAL")]))
    except CatalogError:
        pass
    else:
        raise AssertionError("Invalid USDA nutrient accepted")


def response(request):
    assert request.url.host == "api.nal.usda.gov"
    assert request.url.params["api_key"] == "fixture-private-key"
    if request.url.path.endswith("/search"):
        return httpx.Response(200, json={"foods": [raw], "totalPages": 2})
    return httpx.Response(200, json=raw)


with httpx.Client(transport=httpx.MockTransport(response)) as external:
    provider = USDAClient("fixture-private-key", external)
    assert provider.search("oats")[1]
    assert provider.food(123456)["carbs"] == 60
    with (
        TestClient(app) as client,
        patch.object(routes, "client", return_value=provider),
    ):
        sign_in(client, 1)
        assert client.get("/food/catalog").status_code == 200
        search = client.get("/food/catalog?q=oats")
        assert (
            "Fixture oats" in search.text and "fixture-private-key" not in search.text
        )
        review = client.get("/food/catalog/123456")
        assert review.status_code == 200 and "100 g" in review.text
        token = re.search(r'name="review_token" value="([^"]+)"', review.text).group(1)
        assert (
            client.post(
                "/food/catalog/save",
                data={"review_token": token},
                follow_redirects=False,
            ).status_code
            == 303
        )
        assert (
            client.post(
                "/food/catalog/save",
                data={"review_token": token},
                follow_redirects=False,
            ).status_code
            == 303
        )
        with database.SessionLocal() as db:
            foods = (
                db.query(models.FoodItem)
                .filter_by(user_id=1, source="usda", external_id="123456")
                .all()
            )
            assert len(foods) == 1
            food = foods[0]
            assert food.sodium == 200 and food.sugar is None
            identifier = food.id
            food.name = "My corrected food"
            db.commit()
        # Re-saving must preserve edits, and saving a food must not log a meal.
        assert (
            client.post(
                "/food/catalog/save",
                data={"review_token": token},
                follow_redirects=False,
            ).status_code
            == 303
        )
        with database.SessionLocal() as db:
            assert db.get(models.FoodItem, identifier).name == "My corrected food"
            assert (
                db.query(models.FoodEntry).filter_by(food_item_id=identifier).count()
                == 0
            )
        # Existing meal logging scales imported per-100-g values correctly.
        assert (
            client.post(
                "/food/quick-log",
                data={
                    "food_item_id": identifier,
                    "amount": 25,
                    "unit": "g",
                    "timestamp": "2026-11-02T10:00",
                },
                follow_redirects=False,
            ).status_code
            == 303
        )
        with database.SessionLocal() as db:
            entry = db.query(models.FoodEntry).filter_by(food_item_id=identifier).one()
            assert entry.nutrition_snapshot["totals"]["calories"] == 100
            assert entry.nutrition_snapshot["totals"]["carbs"] == 15
            db.get(models.FoodItem, identifier).active = False
            db.commit()
        assert (
            client.post("/food/catalog/save", data={"review_token": token}).status_code
            == 409
        )
        assert (
            client.post(
                "/food/catalog/save", data={"review_token": token + "tampered"}
            ).status_code
            == 400
        )
        with patch(
            "itsdangerous.URLSafeTimedSerializer.loads",
            side_effect=SignatureExpired("fixture"),
        ):
            assert (
                client.post(
                    "/food/catalog/save", data={"review_token": token}
                ).status_code
                == 400
            )
        sign_in(client, 2)
        assert (
            client.post("/food/catalog/save", data={"review_token": token}).status_code
            == 400
        )
        second = client.get("/food/catalog/123456")
        own_token = re.search(
            r'name="review_token" value="([^"]+)"', second.text
        ).group(1)
        assert (
            client.post(
                "/food/catalog/save",
                data={"review_token": own_token},
                follow_redirects=False,
            ).status_code
            == 303
        )
        assert client.get("/food/catalog?q=" + "a" * 121).status_code == 422
        assert client.get("/food/catalog?page=101").status_code == 422
        with patch.object(
            provider, "search", side_effect=CatalogError("Temporarily unavailable")
        ):
            assert "Temporarily unavailable" in client.get("/food/catalog?q=oats").text

with RawClient(app) as client:
    sign_in(client, 1)
    assert (
        client.post("/food/catalog/save", data={"review_token": token}).status_code
        == 403
    )
for status in (403, 404, 429, 500):
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                status, json={"api_key": "fixture-private-key"}
            )
        )
    ) as external:
        try:
            USDAClient("fixture-private-key", external).search("oats")
        except CatalogError as exc:
            assert "fixture-private-key" not in str(exc)
        else:
            raise AssertionError("Provider failure accepted")
try:
    USDAClient("").search("oats")
except CatalogError:
    pass
else:
    raise AssertionError("Missing key accepted")
print(
    "PASS: USDA nutrient units/100-g basis/unknowns; review and save; scaling; repeated saves preserve edits; account/CSRF/token/trash protection; safe provider failures."
)
