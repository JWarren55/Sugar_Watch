"""Upgrade an existing schema, retry safely, and enforce new storage guards."""

import os

os.environ["DATABASE_URL"] = "sqlite://"
from datetime import datetime, timedelta

from sqlalchemy import create_engine, inspect, select
from sqlalchemy.exc import IntegrityError

from app.db import models
from app.db.migrations import schema_migrations
from app.db.migrations.health_storage import (
    HEALTH_STORAGE_MIGRATION,
    apply_health_storage_migration,
)

engine = create_engine("sqlite://")
models.User.__table__.create(engine)
schema_migrations.create(engine)
with engine.begin() as db:
    db.execute(
        models.User.__table__.insert(),
        [
            {"id": 1, "google_id": "one", "email": "one@example.test"},
            {"id": 2, "google_id": "two", "email": "two@example.test"},
        ],
    )
apply_health_storage_migration(engine, schema_migrations)
apply_health_storage_migration(engine, schema_migrations)
assert {
    "sleep_intervals",
    "health_metric_samples",
    "health_workouts",
    "health_import_tokens",
} <= set(inspect(engine).get_table_names())
with engine.connect() as db:
    assert db.execute(
        select(schema_migrations.c.name).where(
            schema_migrations.c.name == HEALTH_STORAGE_MIGRATION
        )
    ).scalars().all() == [HEALTH_STORAGE_MIGRATION]
start = datetime(2026, 11, 1, 6)
row = dict(
    user_id=1,
    start_time=start,
    end_time=start + timedelta(hours=1),
    stage="core",
    import_key="same-key",
)
with engine.begin() as db:
    db.execute(models.SleepInterval.__table__.insert(), row)
    db.execute(models.SleepInterval.__table__.insert(), dict(row, user_id=2))
for invalid in (
    row,
    dict(row, import_key="bad-duration", end_time=start),
    dict(row, import_key="bad-stage", stage="invented"),
):
    try:
        with engine.begin() as db:
            db.execute(models.SleepInterval.__table__.insert(), invalid)
    except IntegrityError:
        pass
    else:
        raise AssertionError("Sleep constraint not enforced")
for sample in (
    dict(metric="steps", unit="kg", value=10),
    dict(metric="steps", unit="count", value=-1),
):
    try:
        with engine.begin() as db:
            db.execute(
                models.HealthMetricSample.__table__.insert(),
                dict(user_id=1, start_time=start, end_time=start, **sample),
            )
    except IntegrityError:
        pass
    else:
        raise AssertionError("Metric constraint not enforced")
print(
    "PASS: existing-schema health table creation, journal repeat safety, per-user uniqueness and interval/stage/quantity/unit constraints."
)
