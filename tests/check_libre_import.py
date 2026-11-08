"""Exercise CSV parsing, upload isolation, duplicate protection, and atomic failures."""

import runpy
from datetime import datetime

from tests.support import TestClient, sign_in

state = runpy.run_path("tests/check_sections.py")
app, models, database = state["app"], state["models"], state["database"]

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from app.db.migrations import schema_migrations
from app.db.migrations.integrity import apply_integrity_migration
from app.services.libre_import import parse_libreview

HEADER = "Device,Serial Number,Device Timestamp,Record Type,Historic Glucose mg/dL,Scan Glucose mg/dL\n"
CSV = (
    "Export metadata\n"
    + HEADER
    + "Libre 3,fictional,10-30-2026 10:15,0,123,\n"
    + "Libre 3,fictional,10-30-2026 10:16,1,,145\n"
).encode()
rows, ignored = parse_libreview(CSV, "America/Chicago", "MDY")
assert rows[0]["timestamp"] == datetime(2026, 10, 30, 15, 15)
assert len(rows) == 2 and ignored == 0
metric = (
    CSV.decode()
    .replace("mg/dL", "mmol/L")
    .replace(",123,", ",5.5,")
    .replace(",,145", ",,6.1")
)
assert parse_libreview(metric.encode(), "UTC", "MDY")[0][0]["glucose"] == 99
for bad, zone, order in (
    (CSV.replace(b"123", b"NaN"), "UTC", "MDY"),
    (CSV.replace(b"123", b"HI"), "UTC", "MDY"),
    (CSV.replace(b"10-30-2026 10:15", b"11-01-2026 01:15"), "America/Chicago", "MDY"),
    (CSV, "invalid-zone", "MDY"),
    (CSV, "UTC", "invalid"),
):
    try:
        parse_libreview(bad, zone, order)
    except ValueError:
        pass
    else:
        raise AssertionError("Invalid import accepted")

with TestClient(app) as client:
    sign_in(client, 1)

    def upload(content=CSV):
        return client.post(
            "/glucose/import/libreview",
            data={"timezone_name": "America/Chicago", "date_order": "MDY"},
            files={"file": ("fictional.csv", content, "text/csv")},
            follow_redirects=False,
        )

    response = upload()
    assert response.status_code == 303, response.text
    assert "imported=2&skipped=0" in response.headers["location"]
    assert "imported=0&skipped=2" in upload().headers["location"]
    with database.SessionLocal() as db:
        reading = (
            db.query(models.GlucoseReading)
            .filter_by(source="libreview", user_id=1)
            .first()
        )
        reading.active = False
        db.commit()
    assert "imported=0&skipped=2" in upload().headers["location"]
    with database.SessionLocal() as db:
        before = db.query(models.GlucoseReading).count()
    invalid = CSV + b"Libre 3,fictional,10-30-2026 10:17,0,invalid,\n"
    assert upload(invalid).status_code == 400
    with database.SessionLocal() as db:
        assert db.query(models.GlucoseReading).count() == before
    sign_in(client, 2)
    assert "imported=2&skipped=0" in upload().headers["location"]
    with database.SessionLocal() as db:
        assert (
            db.query(models.GlucoseReading)
            .filter_by(source="libreview", user_id=2)
            .count()
            == 2
        )


# Upgrade an old schema, retry safely, and reject duplicates without removing data.
def old_schema(duplicate=False):
    engine = create_engine("sqlite://")
    with engine.begin() as db:
        db.execute(
            text(
                "CREATE TABLE health_profile (id INTEGER PRIMARY KEY, user_id INTEGER, active BOOLEAN)"
            )
        )
        db.execute(
            text(
                "CREATE TABLE favorite_foods (id INTEGER PRIMARY KEY, user_id INTEGER, food_item_id INTEGER)"
            )
        )
        db.execute(
            text(
                "CREATE TABLE glucose_readings (id INTEGER PRIMARY KEY, user_id INTEGER)"
            )
        )
        db.execute(text("INSERT INTO health_profile VALUES (1,1,1), (2,1,0)"))
        if duplicate:
            db.execute(text("INSERT INTO health_profile VALUES (3,1,1)"))
    schema_migrations.create(engine)
    return engine


engine = old_schema()
apply_integrity_migration(engine, schema_migrations)
apply_integrity_migration(engine, schema_migrations)
for sql in (
    "INSERT INTO health_profile (id,user_id,active) VALUES (3,1,1)",
    "INSERT INTO favorite_foods VALUES (1,1,2), (2,1,2)",
    "INSERT INTO glucose_readings (id,user_id,import_key) VALUES (1,1,'abc'), (2,1,'abc')",
):
    try:
        with engine.begin() as db:
            db.execute(text(sql))
    except IntegrityError:
        pass
    else:
        raise AssertionError("Duplicate accepted by database")
engine = old_schema(duplicate=True)
try:
    apply_integrity_migration(engine, schema_migrations)
except RuntimeError as exc:
    assert "health_profile" in str(exc)
else:
    raise AssertionError("Conflicting legacy profiles accepted")
assert "active_profile_user_id" not in {
    c["name"] for c in inspect(engine).get_columns("health_profile")
}
with engine.connect() as db:
    assert db.scalar(text("SELECT COUNT(*) FROM health_profile")) == 3
print(
    "PASS: Libre parsing/UTC/units; invalid data and DST rejection; atomic upload; repeat/soft-delete/account isolation; old-schema migration and uniqueness guards."
)
