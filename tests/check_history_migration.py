"""Check legacy timestamp and food-snapshot backfills without touching MySQL."""

import os
from datetime import datetime

os.environ["DATABASE_URL"] = "sqlite://"
from sqlalchemy import create_engine, event, select, text

import models
from migrations import (
    HEIGHT_INCHES_MIGRATION,
    HISTORY_MIGRATION,
    apply_storage_migrations,
    schema_migrations,
)


def fixture():
    engine = create_engine("sqlite://")
    models.Base.metadata.create_all(engine)
    schema_migrations.create(engine)
    with engine.begin() as connection:
        connection.execute(
            schema_migrations.insert().values(
                name=HEIGHT_INCHES_MIGRATION,
                applied_at=datetime(2026, 10, 21),
                details="{}",
            )
        )
        connection.execute(
            models.User.__table__.insert(),
            {"id": 1, "google_id": "legacy", "email": "legacy@example.test"},
        )
        connection.execute(
            models.FoodItem.__table__.insert(),
            {
                "id": 1,
                "user_id": 1,
                "name": "Legacy food",
                "serving_size": 1,
                "serving_unit": "oz",
                "calories": 100,
            },
        )
        connection.execute(
            models.FoodEntry.__table__.insert(),
            {
                "id": 1,
                "user_id": 1,
                "food_item_id": 1,
                "timestamp": datetime(2026, 10, 19, 14, 30),
                "amount": 2,
                "unit": "oz",
                "active": False,
            },
        )
        connection.execute(
            models.GlucoseReading.__table__.insert(),
            {
                "id": 1,
                "user_id": 1,
                "glucose": 123,
                "timestamp": datetime(2026, 1, 19, 14, 30),
                "active": True,
            },
        )
        # Simulate the actual old schema before the new columns existed.
        connection.execute(
            text("ALTER TABLE food_entries DROP COLUMN nutrition_snapshot")
        )
        for model in (
            models.HealthHistory,
            models.FoodEntry,
            models.ExerciseEntry,
            models.MedicationEntry,
            models.MoodEntry,
            models.GlucoseReading,
            models.FoodItem,
        ):
            connection.execute(
                text("ALTER TABLE " + model.__tablename__ + " DROP COLUMN deleted_at")
            )
    return engine


engine = fixture()
apply_storage_migrations(engine)
with engine.connect() as connection:
    food = connection.execute(select(models.FoodEntry.__table__)).mappings().one()
    assert food["timestamp"] == datetime(2026, 10, 19, 19, 30)
    assert (
        food["unit"] == "g" and food["nutrition_snapshot"]["totals"]["calories"] == 200
    )
    assert food["active"] is False and food["deleted_at"] is None
    glucose = (
        connection.execute(select(models.GlucoseReading.__table__)).mappings().one()
    )
    assert glucose["timestamp"] == datetime(2026, 1, 19, 20, 30)
    before = dict(food)
apply_storage_migrations(engine)
with engine.connect() as connection:
    assert (
        dict(connection.execute(select(models.FoodEntry.__table__)).mappings().one())
        == before
    )

engine = fixture()


def fail_marker(connection, cursor, statement, parameters, context, executemany):
    if statement.startswith("INSERT INTO schema_migrations"):
        raise RuntimeError("Simulated journal failure")


event.listen(engine, "before_cursor_execute", fail_marker)
try:
    apply_storage_migrations(engine)
except RuntimeError as exc:
    assert str(exc) == "Simulated journal failure"
else:
    raise AssertionError("The simulated failure did not run")
finally:
    event.remove(engine, "before_cursor_execute", fail_marker)
with engine.connect() as connection:
    food = connection.execute(select(models.FoodEntry.__table__)).mappings().one()
    assert food["timestamp"] == datetime(2026, 10, 19, 14, 30)
    assert food["unit"] == "oz" and food["nutrition_snapshot"] is None
    assert (
        connection.scalar(
            select(schema_migrations.c.name).where(
                schema_migrations.c.name == HISTORY_MIGRATION
            )
        )
        is None
    )
apply_storage_migrations(engine)
print(
    "PASS: legacy-column upgrades; Chicago DST conversion; inactive entry snapshots; repeat safety; transactional rollback and retry."
)
