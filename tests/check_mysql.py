"""Verify real MySQL schema and INSERTs inside a rolled-back transaction."""

from datetime import date, datetime
from uuid import uuid4

from sqlalchemy import func, inspect, select
from sqlalchemy.orm import Session

import models
from database import engine


def check():
    if engine.dialect.name != "mysql":
        raise RuntimeError("This check requires the configured MySQL database.")
    inspector = inspect(engine)
    expected = models.Base.metadata.tables
    actual = set(inspector.get_table_names())
    missing = set(expected) - actual
    assert not missing, "Missing tables: " + ", ".join(sorted(missing))
    for name, table in expected.items():
        columns = {column["name"] for column in inspector.get_columns(name)}
        assert set(table.columns.keys()) <= columns, "Missing columns in " + name
        assert (
            inspector.get_table_options(name).get("mysql_engine", "").lower()
            == "innodb"
        ), "Rollback check requires InnoDB"
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            with Session(
                bind=connection, join_transaction_mode="create_savepoint"
            ) as db:
                key = "progress1-check-" + uuid4().hex
                user = models.User(
                    google_id=key,
                    email=key + "@example.test",
                    name="Temporary verification",
                )
                db.add(user)
                db.flush()
                user_id = user.id
                food = models.FoodItem(
                    user_id=user_id,
                    name="Temporary oats",
                    serving_size=40,
                    serving_unit="g",
                    calories=150,
                    source="manual",
                )
                db.add(food)
                db.flush()
                stamp = datetime.now().replace(microsecond=0)
                db.add_all(
                    [
                        models.HealthProfile(
                            user_id=user_id,
                            height=177.8,
                            sex="Male",
                            date_of_birth=date(1990, 1, 1),
                            preferred_units="imperial",
                        ),
                        models.HealthHistory(
                            user_id=user_id, timestamp=stamp, weight=180, waist=34
                        ),
                        models.FoodEntry(
                            user_id=user_id,
                            food_item_id=food.id,
                            timestamp=stamp,
                            amount=40,
                            unit="g",
                        ),
                        models.FavoriteFood(user_id=user_id, food_item_id=food.id),
                        models.ExerciseEntry(
                            user_id=user_id,
                            timestamp=stamp,
                            length_minutes=30,
                            exercise_type="Cardio",
                            intensity="Low",
                            distance=1,
                        ),
                        models.MedicationEntry(
                            user_id=user_id,
                            timestamp=stamp,
                            medication_name="Temporary example",
                            dose=1,
                            unit="mg",
                        ),
                        models.MoodEntry(
                            user_id=user_id, timestamp=stamp, feeling="Good"
                        ),
                        models.GlucoseReading(
                            user_id=user_id,
                            timestamp=stamp,
                            glucose=110,
                            source="manual",
                        ),
                    ]
                )
                db.flush()
                for table in expected.values():
                    owner = table.c.id if table.name == "users" else table.c.user_id
                    assert (
                        db.scalar(
                            select(func.count())
                            .select_from(table)
                            .where(owner == user_id)
                        )
                        >= 1
                    )
                print(
                    "PASS: MySQL connection, all model columns, and INSERT/SELECT in every table."
                )
        finally:
            transaction.rollback()
    with engine.connect() as connection:
        assert (
            connection.scalar(
                select(func.count())
                .select_from(models.User)
                .where(models.User.google_id == key)
            )
            == 0
        )
    print("PASS: verification transaction rolled back; no test records retained.")
    print("Verified tables: " + ", ".join(sorted(expected)))


if __name__ == "__main__":
    check()
