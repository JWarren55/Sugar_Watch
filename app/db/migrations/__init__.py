"""Apply recorded storage migrations before the app accepts requests."""

import json
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, MetaData, String, Table, Text, select, text

from app.db import models

HEIGHT_INCHES_MIGRATION = "20261021_height_inches"
migration_metadata = MetaData()
schema_migrations = Table(
    "schema_migrations",
    migration_metadata,
    Column("name", String(100), primary_key=True),
    Column("applied_at", DateTime, nullable=False),
    Column("details", Text, nullable=False),
)


def _apply_height_migration(engine):
    # Lock MySQL migration work so two app processes cannot convert the same data.
    with engine.connect() as connection:
        mysql = connection.dialect.name == "mysql"
        locked = False
        try:
            if mysql:
                locked = (
                    connection.scalar(
                        text("SELECT GET_LOCK(:name, 30)"),
                        {"name": "sugar_watch_height_inches"},
                    )
                    == 1
                )
                if not locked:
                    raise RuntimeError("Could not acquire the storage migration lock.")
                connection.commit()

            # Create the journal before beginning the data conversion transaction.
            schema_migrations.create(bind=connection, checkfirst=True)
            connection.commit()
            with connection.begin():
                applied = connection.scalar(
                    select(schema_migrations.c.name).where(
                        schema_migrations.c.name == HEIGHT_INCHES_MIGRATION
                    )
                )
                if applied:
                    return 0

                # Back up every original height, including inactive profiles.
                profiles = models.HealthProfile.__table__
                rows = connection.execute(
                    select(profiles.c.id, profiles.c.height).order_by(profiles.c.id)
                ).all()
                originals = [
                    {"profile_id": row.id, "height_cm": row.height} for row in rows
                ]
                connection.execute(
                    profiles.update().values(height=profiles.c.height / 2.54)
                )

                # Save the backup and marker in the same transaction as the update.
                connection.execute(
                    schema_migrations.insert().values(
                        name=HEIGHT_INCHES_MIGRATION,
                        applied_at=datetime.now(timezone.utc).replace(tzinfo=None),
                        details=json.dumps(
                            {
                                "from_unit": "cm",
                                "to_unit": "inches",
                                "original_heights": originals,
                            }
                        ),
                    )
                )
                return len(rows)
        finally:
            if locked:
                connection.execute(
                    text("SELECT RELEASE_LOCK(:name)"),
                    {"name": "sugar_watch_height_inches"},
                )


HISTORY_MIGRATION = "20261021_utc_nutrition_trash"


def _apply_history_migration(engine):
    # MySQL DDL is separate from the atomic timestamp and snapshot backfill.
    from types import SimpleNamespace

    from sqlalchemy import inspect
    from sqlalchemy.schema import CreateColumn

    from app.services.nutrition import from_food
    from app.utils.time_utils import LEGACY_TIMEZONE, to_utc

    tracked = (
        models.HealthHistory,
        models.FoodEntry,
        models.ExerciseEntry,
        models.MedicationEntry,
        models.MoodEntry,
        models.GlucoseReading,
        models.FoodItem,
    )
    with engine.connect() as connection:
        locked = False
        try:
            if connection.dialect.name == "mysql":
                locked = (
                    connection.scalar(
                        text("SELECT GET_LOCK(:name, 30)"),
                        {"name": "sugar_watch_history_v1"},
                    )
                    == 1
                )
                connection.commit()
                if not locked:
                    raise RuntimeError("Could not acquire the history migration lock.")
            quote = connection.dialect.identifier_preparer.quote
            for model in tracked:
                existing = {
                    item["name"]
                    for item in inspect(connection).get_columns(model.__tablename__)
                }
                for name in ("deleted_at", "nutrition_snapshot"):
                    if name in model.__table__.columns and name not in existing:
                        definition = str(
                            CreateColumn(model.__table__.columns[name]).compile(
                                dialect=connection.dialect
                            )
                        )
                        connection.execute(
                            text(
                                "ALTER TABLE "
                                + quote(model.__tablename__)
                                + " ADD COLUMN "
                                + definition
                            )
                        )
                        connection.commit()
            connection.commit()
            with connection.begin():
                if connection.scalar(
                    select(schema_migrations.c.name).where(
                        schema_migrations.c.name == HISTORY_MIGRATION
                    )
                ):
                    return
                counts = {}
                for model in tracked:
                    table = model.__table__
                    if "timestamp" not in table.columns:
                        continue
                    rows = connection.execute(
                        select(table.c.id, table.c.timestamp)
                    ).all()
                    for row in rows:
                        connection.execute(
                            table.update()
                            .where(table.c.id == row.id)
                            .values(timestamp=to_utc(row.timestamp, LEGACY_TIMEZONE))
                        )
                    counts[table.name] = len(rows)
                foods = {
                    row["id"]: SimpleNamespace(**dict(row))
                    for row in connection.execute(
                        select(models.FoodItem.__table__)
                    ).mappings()
                }
                entries = models.FoodEntry.__table__
                for row in connection.execute(select(entries)).mappings():
                    if row["nutrition_snapshot"] is None:
                        snapshot = from_food(
                            foods.get(row["food_item_id"]),
                            row["amount"],
                            row["unit"],
                            strict=False,
                        )
                        connection.execute(
                            entries.update()
                            .where(entries.c.id == row["id"])
                            .values(
                                nutrition_snapshot=snapshot,
                                amount=snapshot["amount"],
                                unit=snapshot["unit"],
                            )
                        )
                connection.execute(
                    schema_migrations.insert().values(
                        name=HISTORY_MIGRATION,
                        applied_at=datetime.now(timezone.utc).replace(tzinfo=None),
                        details=json.dumps(
                            {
                                "legacy_timezone": LEGACY_TIMEZONE,
                                "timestamp_counts": counts,
                                "nutrition_backfill": "Current saved food definitions; original label units retained.",
                            }
                        ),
                    )
                )
        finally:
            if locked:
                connection.execute(
                    text("SELECT RELEASE_LOCK(:name)"),
                    {"name": "sugar_watch_history_v1"},
                )


def apply_storage_migrations(engine):
    converted = _apply_height_migration(engine)
    _apply_history_migration(engine)
    from app.db.migrations.integrity import apply_integrity_migration

    apply_integrity_migration(engine, schema_migrations)
    from app.db.migrations.health_storage import apply_health_storage_migration

    apply_health_storage_migration(engine, schema_migrations)
    from app.db.migrations.shortcuts import apply_shortcut_migration

    apply_shortcut_migration(engine, schema_migrations)
    from app.db.migrations.email_signup import apply_signup_migration

    apply_signup_migration(engine, schema_migrations)
    models.NutritionGoal.__table__.create(engine, checkfirst=True)
    models.OpenAICredential.__table__.create(engine, checkfirst=True)
    return converted
