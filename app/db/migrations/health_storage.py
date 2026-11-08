"""Create Apple Health storage without converting existing tracking records."""

import json
from datetime import datetime, timezone

from sqlalchemy import select, text

from app.db import models

HEALTH_STORAGE_MIGRATION = "20261102_apple_health_storage"


def apply_health_storage_migration(engine, journal):
    with engine.connect() as db:
        locked = False
        try:
            if db.dialect.name == "mysql":
                locked = (
                    db.scalar(text("SELECT GET_LOCK('sugar_watch_health_storage', 30)"))
                    == 1
                )
                db.commit()
                if not locked:
                    raise RuntimeError(
                        "Could not acquire the health storage migration lock."
                    )
            for model in (
                models.SleepInterval,
                models.HealthMetricSample,
                models.HealthWorkout,
                models.HealthImportToken,
            ):
                model.__table__.create(db, checkfirst=True)
                db.commit()
            if not db.scalar(
                select(journal.c.name).where(journal.c.name == HEALTH_STORAGE_MIGRATION)
            ):
                db.execute(
                    journal.insert().values(
                        name=HEALTH_STORAGE_MIGRATION,
                        applied_at=datetime.now(timezone.utc).replace(tzinfo=None),
                        details=json.dumps(
                            {
                                "tables": [
                                    "sleep_intervals",
                                    "health_metric_samples",
                                    "health_workouts",
                                    "health_import_tokens",
                                ],
                                "timestamps": "UTC",
                                "existing_records": "unchanged",
                            }
                        ),
                    )
                )
            db.commit()
        finally:
            if locked:
                db.execute(text("SELECT RELEASE_LOCK('sugar_watch_health_storage')"))
