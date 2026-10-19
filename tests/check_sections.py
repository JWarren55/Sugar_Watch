"""Integration checks using an isolated in-memory database; no Google or MySQL access."""

import os

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["SECRET_KEY"] = "integration-test"
import base64
import json
from collections import Counter
from html.parser import HTMLParser

from itsdangerous import TimestampSigner
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

import database

# Configure the isolated database before importing application modules.
database.engine = create_engine(
    "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
)
database.SessionLocal.configure(bind=database.engine)
from fastapi.testclient import TestClient

import models
from main import app


class Forms(HTMLParser):
    def __init__(self):
        super().__init__()
        self.actions = []
        self.links = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "form":
            self.actions.append(
                (attrs.get("method", "get").upper(), attrs.get("action"))
            )
        if tag == "a":
            self.links.append(attrs.get("href"))


with database.SessionLocal() as db:
    db.add_all(
        [
            models.User(
                id=1, google_id="test1", email="one@example.test", name="Test One"
            ),
            models.User(
                id=2, google_id="test2", email="two@example.test", name="Test Two"
            ),
        ]
    )
    db.commit()

from routes import auth, exercise, food, glucose, health, home, medication, mood

routes = Counter(
    (method, route.path)
    for module in (home, auth, glucose, food, exercise, medication, health, mood)
    for route in module.router.routes
    for method in route.methods
)
assert not [key for key, count in routes.items() if count > 1], "Duplicate routes"
sections = {
    "glucose": "Glucose",
    "food": "Food",
    "exercise": "Exercise",
    "medication": "Medication Entries",
    "health": "Health Profile and Measurements",
    "mood": "Mood Entries",
}
stamp = "2026-10-19T14:30"
with TestClient(app) as client:
    for section in sections:
        r = client.get("/" + section, follow_redirects=False)
        assert r.is_redirect and r.headers["location"] == "/login", (section, r.text)

    def sign_in(user_id):
        payload = base64.b64encode(json.dumps({"user_id": user_id}).encode())
        client.cookies.set(
            "session", TimestampSigner("integration-test").sign(payload).decode()
        )

    sign_in(1)
    home = client.get("/")
    assert home.status_code == 200 and "<h1>Sugar Watch</h1>" in home.text
    for section, heading in sections.items():
        assert 'href="/' + section + '"' in home.text
        r = client.get("/" + section)
        assert r.status_code == 200 and "<h1>" + heading + "</h1>" in r.text, (
            section,
            r.text,
        )
        parser = Forms()
        parser.feed(r.text)
        assert "/" in parser.links, section
        for method, action in parser.actions:
            assert (method, action) in routes, (section, method, action)

    def post(path, data):
        r = client.post(path, data=data, follow_redirects=False)
        assert r.status_code == 303, (path, r.status_code, r.text)
        page = client.get(r.headers["location"])
        assert page.status_code == 200
        return page.text

    assert "143" in post("/glucose", {"timestamp": stamp, "glucose": 143})
    assert "Cardio" in post(
        "/exercise",
        {
            "timestamp": stamp,
            "length_minutes": 31,
            "exercise_type": "Cardio",
            "intensity": "Medium",
            "distance": "",
            "average_heart_rate": "",
            "peak_heart_rate": "",
        },
    )
    assert "Test medication" in post(
        "/medication",
        {
            "timestamp": stamp,
            "medication_name": "Test medication",
            "dose": 12,
            "unit": "mg",
        },
    )
    assert "Optional dose" in post(
        "/medication",
        {
            "timestamp": stamp,
            "medication_name": "Optional dose",
            "dose": "",
            "unit": "",
        },
    )
    assert "Great" in post(
        "/mood", {"timestamp": stamp, "feeling": "Great", "hunger": "", "head": ""}
    )
    assert 'id="height-unit">inches</span>' in client.get("/health").text
    assert "Update Profile" in post(
        "/health/profile",
        {
            "height": 70,
            "sex": "Male",
            "date_of_birth": "1990-01-01",
            "preferred_units": "imperial",
        },
    )
    with database.SessionLocal() as db:
        assert abs(db.query(models.HealthProfile).one().height - 177.8) < 1e-9
    assert 'value="70.0"' in client.get("/health").text
    post(
        "/health/profile",
        {
            "height": 176,
            "sex": "Male",
            "date_of_birth": "1990-01-01",
            "preferred_units": "metric",
        },
    )
    with database.SessionLocal() as db:
        assert db.query(models.HealthProfile).one().height == 176
    assert 'id="height-unit">cm</span>' in client.get("/health").text
    # Existing centimeter values must render as inches when Imperial is selected.
    with database.SessionLocal() as db:
        profile = db.query(models.HealthProfile).one()
        profile.height = 177.8
        profile.preferred_units = "imperial"
        db.commit()
    assert 'value="70.0"' in client.get("/health").text
    assert "180" in post(
        "/health/measurements", {"timestamp": stamp, "weight": 180, "waist": ""}
    )
    assert "Test oats" in post(
        "/food/create",
        {"name": "Test oats", "serving_size": 40, "serving_unit": "g", "calories": 150},
    )
    with database.SessionLocal() as db:
        food_id = db.query(models.FoodItem).one().id
    post("/food/quick-log", {"food_item_id": food_id, "amount": 40, "unit": "g"})
    post("/food/favorite", {"food_item_id": food_id})
    post("/food/log-multiple", {"food_item_id": food_id, "amount": 80, "unit": "g"})
    assert (
        client.post(
            "/medication",
            data={"timestamp": stamp, "medication_name": " ", "dose": "", "unit": ""},
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/medication",
            data={
                "timestamp": stamp,
                "medication_name": "Test",
                "dose": -1,
                "unit": "mg",
            },
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/health/measurements", data={"timestamp": stamp, "weight": "", "waist": ""}
        ).status_code
        == 400
    )
    sign_in(2)
    for path, private_value in [
        ("/medication", "Test medication"),
        ("/glucose", "143 mg/dL"),
        ("/mood", "<td>Great</td>"),
        ("/health", "176.0"),
        ("/food", "Test oats"),
    ]:
        assert private_value not in client.get(path).text, path
with database.SessionLocal() as db:
    for model, count in [
        (models.ExerciseEntry, 1),
        (models.MedicationEntry, 2),
        (models.MoodEntry, 1),
        (models.HealthProfile, 1),
        (models.HealthHistory, 1),
        (models.GlucoseReading, 1),
        (models.FoodEntry, 2),
    ]:
        assert db.query(model).count() == count, model.__name__
print(
    "PASS: all six pages, navigation, unique routes, login protection, saves/history, profile updates, optional fields, validation, and user isolation."
)
