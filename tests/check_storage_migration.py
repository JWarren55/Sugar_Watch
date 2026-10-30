"""Check the one-time height conversion using isolated SQLite databases."""

import json
import os
from datetime import date
from math import isclose

os.environ["DATABASE_URL"] = "sqlite://"

from sqlalchemy import create_engine, event, select

import models
from migrations import (
    HEIGHT_INCHES_MIGRATION,
    apply_storage_migrations,
    schema_migrations,
)
from units import to_display, to_storage


def fixture():
    engine = create_engine("sqlite://")
    models.Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            models.User.__table__.insert(),
            {"id": 1, "google_id": "migration-test", "email": "migration@example.test"},
        )
        connection.execute(
            models.HealthProfile.__table__.insert(),
            [
                {
                    "id": 1,
                    "user_id": 1,
                    "height": 177.8,
                    "sex": "Male",
                    "date_of_birth": date(1990, 1, 1),
                    "preferred_units": "imperial",
                    "active": True,
                },
                {
                    "id": 2,
                    "user_id": 1,
                    "height": 165.1,
                    "sex": "Male",
                    "date_of_birth": date(1990, 1, 1),
                    "preferred_units": "metric",
                    "active": False,
                },
            ],
        )
    return engine


engine = fixture()
assert apply_storage_migrations(engine) == 2
with engine.connect() as connection:
    profiles = connection.execute(
        select(models.HealthProfile.__table__).order_by(models.HealthProfile.id)
    ).all()
    assert isclose(profiles[0].height, 70)
    assert isclose(profiles[1].height, 65)
    assert profiles[1].active is False and profiles[1].preferred_units == "metric"
    backup = json.loads(connection.scalar(select(schema_migrations.c.details)))
    assert backup["original_heights"] == [
        {"profile_id": 1, "height_cm": 177.8},
        {"profile_id": 2, "height_cm": 165.1},
    ]
assert apply_storage_migrations(engine) == 0
with engine.connect() as connection:
    assert (
        connection.scalar(
            select(models.HealthProfile.height).where(models.HealthProfile.id == 1)
        )
        == 70
    )

# A failed journal insert must also roll back the height update.
engine = fixture()


def fail_journal(connection, cursor, statement, parameters, context, executemany):
    if statement.startswith("INSERT INTO schema_migrations"):
        raise RuntimeError("Simulated migration failure")


event.listen(engine, "before_cursor_execute", fail_journal)
try:
    apply_storage_migrations(engine)
except RuntimeError as exc:
    assert str(exc) == "Simulated migration failure"
else:
    raise AssertionError("The simulated failure did not occur")
finally:
    event.remove(engine, "before_cursor_execute", fail_journal)
with engine.connect() as connection:
    assert (
        connection.scalar(
            select(models.HealthProfile.height).where(models.HealthProfile.id == 1)
        )
        == 177.8
    )
    assert connection.scalar(select(schema_migrations.c.name)) is None
assert apply_storage_migrations(engine) == 2

# A fresh database records the migration before storing any new inch values.
engine = create_engine("sqlite://")
models.Base.metadata.create_all(engine)
assert apply_storage_migrations(engine) == 0
with engine.begin() as connection:
    connection.execute(
        models.HealthProfile.__table__.insert(),
        {
            "user_id": 1,
            "height": 70,
            "sex": "Male",
            "date_of_birth": date(1990, 1, 1),
            "preferred_units": "imperial",
        },
    )
assert apply_storage_migrations(engine) == 0
with engine.connect() as connection:
    assert connection.scalar(select(models.HealthProfile.height)) == 70
    assert (
        connection.scalar(select(schema_migrations.c.name)) == HEIGHT_INCHES_MIGRATION
    )

assert to_storage(70, "height", "imperial") == 70
assert isclose(to_storage(177.8, "height", "metric"), 70)
assert isclose(to_display(70, "height", "metric"), 177.8)
assert to_display(70, "height", "imperial") == 70
print(
    "PASS: legacy and inactive heights; original-value backup; repeat safety; failure rollback; fresh databases; Metric conversion."
)
